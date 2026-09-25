"""O'qitish va komplayens API — /api/v1/training/...

/my/...      — xodimning o'z kabineti (training.view)
/courses...  — kurs, dars, test boshqaruvi (training.manage)
/assignments, /standards — topshiriq va standartlar
/report/...  — kim nimani ko'rdi, kim ko'rmadi (training.review yoki training.manage)
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Optional

from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from ninja import File, Router, Schema
from ninja.errors import HttpError
from ninja.files import UploadedFile

from core.audit import record
from core.auth import auth, require_module, require_perm
from core.models import Role, User

from . import media, services
from .models import (
    Assignment,
    Course,
    Enrollment,
    EnrollmentStatus,
    Lesson,
    LessonFile,
    LessonProgress,
    Question,
    Quiz,
    QuizAttempt,
    Standard,
    StandardAck,
    Submission,
    SubmissionFile,
    SubmissionStatus,
)

router = Router(tags=["training"])

VIDEO_EXT = {"mp4", "webm", "mov", "m4v", "ogg"}
IMAGE_EXT = {"jpg", "jpeg", "png", "webp", "gif"}
MAX_VIDEO_MB = 500
MAX_FILE_MB = 50


def _guard(request, perm: str):
    require_module(request, "training")
    require_perm(request, perm)


def _can(request, code: str) -> bool:
    return request.auth.has_perm_code(code)


def _ext(f: UploadedFile) -> str:
    return (f.name or "").lower().rsplit(".", 1)[-1]


def _check_file(f: UploadedFile, kinds: set[str] | None = None, max_mb: int = MAX_FILE_MB):
    if kinds and _ext(f) not in kinds:
        raise HttpError(400, f"Bu fayl turi mos emas. Ruxsat: {', '.join(sorted(kinds))}")
    if f.size and f.size > max_mb * 1024 * 1024:
        raise HttpError(400, f"Fayl juda katta — {max_mb} MB dan oshmasin.")


def _url(f) -> Optional[str]:
    return f.url if f else None


def _dt(v) -> Optional[str]:
    return v.isoformat() if v else None


def _umini(u: Optional[User]) -> Optional[dict]:
    return {"id": str(u.pk), "full_name": u.full_name or u.phone, "phone": u.phone,
            "avatar": u.avatar.url if u.avatar else None} if u else None


# ------------------------------------------------------------------ sxemalar
class AudienceIn(Schema):
    roles: list[str] = []
    positions: list[int] = []
    user_ids: list[str] = []
    everyone: bool = False


class CourseIn(AudienceIn):
    title: str
    description: str = ""
    category: str = ""
    is_mandatory: bool = True
    due_days: int = 7
    pass_score: int = 80
    responsible_id: Optional[str] = None
    is_published: bool = False
    certificate: bool = True
    is_archived: bool = False
    cover_url: str = ""


class LessonIn(Schema):
    title: str
    body: str = ""
    checklist: list[str] = []
    video_url: str = ""
    image_url: str = ""
    duration_seconds: int = 0


class LinkIn(Schema):
    url: str
    title: str = ""


class OrderIn(Schema):
    ids: list[int]


class QuizIn(Schema):
    title: str
    lesson_id: Optional[int] = None
    time_limit_seconds: int = 0
    pass_score: int = 0
    max_attempts: int = 0
    shuffle: bool = True


class OptionIn(Schema):
    id: str
    text: str


class QuestionIn(Schema):
    id: Optional[int] = None
    text: str
    options: list[OptionIn]
    correct: list[str]
    explanation: str = ""


class QuestionsIn(Schema):
    questions: list[QuestionIn]


class BeatIn(Schema):
    position: float
    duration: float = 0
    played: float = 0


class AnswersIn(Schema):
    answers: dict[str, list[str]]


class AssignmentIn(AudienceIn):
    title: str
    description: str = ""
    course_id: Optional[int] = None
    due_at: Optional[datetime] = None
    requires_proof: bool = True
    responsible_id: Optional[str] = None
    is_active: bool = True
    media_url: str = ""


class SubmitIn(Schema):
    text: str = ""


class ReviewIn(Schema):
    approve: bool
    note: str = ""


class StandardIn(AudienceIn):
    title: str
    category: str = ""
    body: str = ""
    responsible_id: Optional[str] = None
    is_active: bool = True
    file_url: str = ""


def _user_or_none(uid: Optional[str]) -> Optional[User]:
    if not uid:
        return None
    return User.objects.filter(pk=uid).first()


def _audience(obj) -> dict:
    return {"roles": obj.roles, "positions": obj.positions, "user_ids": [str(x) for x in obj.user_ids], "everyone": obj.everyone}


def _apply(obj, data: Schema, skip: tuple = ()):
    for k, v in data.dict().items():
        if k in skip:
            continue
        if k == "responsible_id":
            obj.responsible = _user_or_none(v)
        elif k == "user_ids":
            obj.user_ids = [str(x) for x in v]
        else:
            setattr(obj, k, v)


# ------------------------------------------------------------------ serializatsiya
def _lesson_out(lesson: Lesson, with_files: bool = True) -> dict:
    out = {
        "id": lesson.pk, "course_id": lesson.course_id, "title": lesson.title, "body": lesson.body,
        "checklist": lesson.checklist, "video": _url(lesson.video), "video_url": lesson.video_url,
        "video_media": media.of(lesson.video, lesson.video_url), "video_mode": lesson.video_mode,
        "image": media.image_src(lesson.image, lesson.image_url), "image_url": lesson.image_url,
        "duration_seconds": lesson.duration_seconds, "sort_order": lesson.sort_order,
        "has_video": lesson.has_video,
    }
    if with_files:
        out["files"] = [{"id": f.pk, "url": f.file.url if f.file else f.url,
                         "title": f.title or (f.file.name.rsplit("/", 1)[-1] if f.file else f.url),
                         "size_bytes": f.size_bytes, "is_image": f.is_image, "is_link": not f.file} for f in lesson.files.all()]
    return out


def _quiz_out(q: Quiz, with_questions: bool = False, admin: bool = False) -> dict:
    out = {"id": q.pk, "course_id": q.course_id, "lesson_id": q.lesson_id, "title": q.title,
           "time_limit_seconds": q.time_limit_seconds, "pass_score": q.effective_pass_score, "own_pass_score": q.pass_score,
           "max_attempts": q.max_attempts, "shuffle": q.shuffle, "questions_count": q.questions.count()}
    if with_questions:
        out["questions"] = [{"id": x.pk, "text": x.text, "options": x.options, "explanation": x.explanation,
                             **({"correct": x.correct} if admin else {"multiple": len(x.correct) > 1})} for x in q.questions.all()]
    return out


def _course_out(c: Course, stats: bool = False) -> dict:
    out = {
        "id": c.pk, "title": c.title, "description": c.description, "category": c.category,
        "cover": media.image_src(c.cover, c.cover_url), "cover_url": c.cover_url,
        "is_mandatory": c.is_mandatory, "due_days": c.due_days, "pass_score": c.pass_score,
        "responsible": _umini(c.responsible), "responsible_id": str(c.responsible_id) if c.responsible_id else None,
        "is_published": c.is_published, "certificate": c.certificate, "is_archived": c.is_archived,
        "sort_order": c.sort_order, **_audience(c),
        "lessons_count": c.lessons.count(), "quizzes_count": c.quizzes.count(),
    }
    if stats:
        ens = Enrollment.objects.filter(course=c)
        out["enrolled"] = ens.count()
        out["completed"] = ens.filter(status=EnrollmentStatus.COMPLETED).count()
        out["overdue"] = ens.exclude(status=EnrollmentStatus.COMPLETED).filter(due_at__lt=timezone.now()).count()
    return out


def _enrollment_card(e: Enrollment, user: User) -> dict:
    c = e.course
    lessons = list(c.lessons.all())
    done = services.lesson_done_ids(user, c)
    nxt = next((les for les in lessons if les.pk not in done), None)
    return {
        "enrollment_id": e.pk, "course": _course_out(c), "status": e.status, "progress": e.progress,
        "lessons_total": len(lessons), "lessons_done": len(done & {les.pk for les in lessons}),
        "due_at": _dt(e.due_at), "is_overdue": e.is_overdue, "completed_at": _dt(e.completed_at),
        "certificate_no": e.certificate_no or None,
        "next_lesson_id": (e.last_lesson_id if e.last_lesson_id and e.last_lesson_id not in done else None) or (nxt.pk if nxt else None),
    }


# ================================================================== XODIM KABINETI
@router.get("/my", auth=auth)
def my_home(request):
    _guard(request, "training.view")
    u = request.auth
    services.sync_user(u, request.tenant)
    ens = list(Enrollment.objects.filter(user=u, course__is_archived=False, course__is_published=True)
               .select_related("course", "course__responsible").order_by("status", "due_at"))
    summary = services.user_summary(u)
    return {
        "user": {"id": str(u.pk), "full_name": u.full_name or u.phone},
        "summary": summary,
        "courses": [_enrollment_card(e, u) for e in ens],
        "certificates": [{"enrollment_id": e.pk, "course_title": e.course.title, "certificate_no": e.certificate_no,
                          "completed_at": _dt(e.completed_at)} for e in ens if e.certificate_no],
        "can": {"manage": _can(request, "training.manage"), "review": _can(request, "training.review") or _can(request, "training.manage")},
    }


def _my_enrollment(request, course: Course) -> Enrollment:
    e = Enrollment.objects.filter(course=course, user=request.auth).first()
    if e is None:
        if _can(request, "training.manage"):     # admin ko'rib chiqish rejimi
            e, _ = services.enroll(course, request.auth)
            return e
        raise HttpError(403, "Bu kurs sizga biriktirilmagan.")
    return e


@router.get("/my/courses/{int:cid}", auth=auth)
def my_course(request, cid: int):
    _guard(request, "training.view")
    c = get_object_or_404(Course, pk=cid, is_archived=False)
    e = _my_enrollment(request, c)
    u = request.auth
    done = services.lesson_done_ids(u, c)
    prog = {p.lesson_id: p for p in LessonProgress.objects.filter(user=u, lesson__course=c)}
    lessons = []
    locked_next = False
    for les in c.lessons.all():
        p = prog.get(les.pk)
        lessons.append({**_lesson_out(les, with_files=False), "percent": p.percent if p else 0,
                        "done": les.pk in done, "locked": locked_next, "opened": p is not None})
        if les.pk not in done:
            locked_next = True
    quizzes = []
    for q in c.quizzes.all():
        best = QuizAttempt.objects.filter(quiz=q, user=u, finished_at__isnull=False).order_by("-score").first()
        lesson_ready = (q.lesson_id in done) if q.lesson_id else len(done) >= len(lessons)
        quizzes.append({**_quiz_out(q), "best_score": best.score if best else None, "passed": bool(best and best.passed),
                        "attempts_left": services.attempts_left(q, u), "locked": not lesson_ready})
    return {**_enrollment_card(e, u), "lessons": lessons, "quizzes": quizzes}


@router.get("/my/lessons/{int:lid}", auth=auth)
def my_lesson(request, lid: int):
    _guard(request, "training.view")
    lesson = get_object_or_404(Lesson.objects.select_related("course"), pk=lid, course__is_archived=False)
    _my_enrollment(request, lesson.course)
    u = request.auth
    done = services.lesson_done_ids(u, lesson.course)
    if services.lesson_locked(lesson, done) and not _can(request, "training.manage"):
        raise HttpError(403, "Avval oldingi darsni tugating.")
    p = services.open_lesson(u, lesson)
    ids = list(lesson.course.lessons.values_list("id", flat=True))
    i = ids.index(lesson.pk)
    cfg = services.conf(request.tenant)
    return {
        **_lesson_out(lesson), "course_title": lesson.course.title, "number": i + 1, "total": len(ids),
        "prev_id": ids[i - 1] if i > 0 else None, "next_id": ids[i + 1] if i + 1 < len(ids) else None,
        "progress": {"percent": p.percent, "max_position": p.max_position, "last_position": p.last_position,
                     "done": p.completed_at is not None},
        "quizzes": [_quiz_out(q) for q in lesson.quizzes.all()],
        "final_quiz_id": lesson.course.quizzes.filter(lesson__isnull=True).values_list("id", flat=True).first() if i + 1 == len(ids) else None,
        "rules": {"min_watch_percent": int(cfg["min_watch_percent"]), "block_seek": bool(cfg["block_seek"])},
    }


@router.post("/my/lessons/{int:lid}/beat", auth=auth)
def my_lesson_beat(request, lid: int, data: BeatIn):
    _guard(request, "training.view")
    lesson = get_object_or_404(Lesson, pk=lid)
    _my_enrollment(request, lesson.course)
    p = services.beat(request.auth, lesson, position=data.position, duration=data.duration, played=data.played, tenant=request.tenant)
    return {"percent": p.percent, "max_position": p.max_position, "done": p.completed_at is not None}


@router.post("/my/lessons/{int:lid}/complete", auth=auth)
def my_lesson_complete(request, lid: int):
    _guard(request, "training.view")
    lesson = get_object_or_404(Lesson, pk=lid)
    _my_enrollment(request, lesson.course)
    if lesson.has_video:
        p = LessonProgress.objects.filter(user=request.auth, lesson=lesson).first()
        if not (p and p.completed_at):
            need = services.conf(request.tenant)["min_watch_percent"]
            raise HttpError(400, f"Videoni oxirigacha ko'ring — kamida {need}% ko'rilishi kerak (hozir {p.percent if p else 0}%).")
    else:
        services.complete_text_lesson(request.auth, lesson)
    e = services.recompute(lesson.course, request.auth)
    return {"ok": True, "progress": e.progress if e else 0}


@router.post("/my/quizzes/{int:qid}/start", auth=auth)
def my_quiz_start(request, qid: int):
    _guard(request, "training.view")
    q = get_object_or_404(Quiz.objects.select_related("course"), pk=qid)
    _my_enrollment(request, q.course)
    left = services.attempts_left(q, request.auth)
    if left == 0:
        raise HttpError(400, "Urinishlar tugadi. Mas'ul bilan bog'laning.")
    if not q.questions.exists():
        raise HttpError(400, "Bu testda hali savol yo'q.")
    a = services.start_attempt(q, request.auth)
    qs = {x.pk: x for x in q.questions.all()}
    questions = []
    for qid_ in a.question_ids:
        x = qs[qid_]
        opts = list(x.options)
        if q.shuffle:
            random.shuffle(opts)
        questions.append({"id": x.pk, "text": x.text, "image": _url(x.image), "options": opts, "multiple": len(x.correct) > 1})
    return {"attempt_id": a.pk, "quiz": _quiz_out(q), "questions": questions, "started_at": a.started_at.isoformat(),
            "attempts_left": left}


@router.post("/my/attempts/{int:aid}/submit", auth=auth)
def my_quiz_submit(request, aid: int, data: AnswersIn):
    _guard(request, "training.view")
    a = get_object_or_404(QuizAttempt.objects.select_related("quiz", "quiz__course"), pk=aid, user=request.auth)
    if a.finished_at:
        raise HttpError(400, "Bu urinish allaqachon yakunlangan.")
    a = services.grade(a, data.answers)
    qs = {x.pk: x for x in a.quiz.questions.all()}
    review = [{"id": qid, "text": qs[qid].text, "options": qs[qid].options, "given": a.answers.get(str(qid), []),
               "correct": qs[qid].correct, "ok": sorted(a.answers.get(str(qid), [])) == sorted(qs[qid].correct),
               "explanation": qs[qid].explanation} for qid in a.question_ids if qid in qs]
    e = Enrollment.objects.filter(course=a.quiz.course, user=request.auth).first()
    return {"score": a.score, "correct": a.correct_count, "total": a.total, "passed": a.passed,
            "pass_score": a.quiz.effective_pass_score, "review": review,
            "attempts_left": services.attempts_left(a.quiz, request.auth),
            "course_completed": bool(e and e.status == EnrollmentStatus.COMPLETED), "enrollment_id": e.pk if e else None}


def _submission_out(s: Submission, admin: bool = False) -> dict:
    a = s.assignment
    return {
        "id": s.pk, "status": s.status, "text": s.text, "submitted_at": _dt(s.submitted_at), "reviewed_at": _dt(s.reviewed_at),
        "review_note": s.review_note, "reviewed_by": _umini(s.reviewed_by), "attempts": s.attempts,
        "files": [{"id": f.pk, "url": f.file.url, "is_image": f.file.name.lower().rsplit(".", 1)[-1] in IMAGE_EXT,
                   "is_video": f.file.name.lower().rsplit(".", 1)[-1] in VIDEO_EXT} for f in s.files.all()],
        "user": _umini(s.user) if admin else None,
        "assignment": {"id": a.pk, "title": a.title, "description": a.description, "media": _url(a.media),
                       "media_is_video": bool(a.media) and a.media.name.lower().rsplit(".", 1)[-1] in VIDEO_EXT,
                       "media_view": media.of(a.media, a.media_url),
                       "due_at": _dt(a.due_at), "requires_proof": a.requires_proof, "responsible": _umini(a.responsible),
                       "is_overdue": bool(a.due_at and a.due_at < timezone.now() and s.status in (SubmissionStatus.TODO, SubmissionStatus.REJECTED))},
    }


@router.get("/my/assignments", auth=auth)
def my_assignments(request):
    _guard(request, "training.view")
    services.sync_user(request.auth, request.tenant)
    subs = Submission.objects.filter(user=request.auth, assignment__is_active=True).select_related("assignment", "assignment__responsible", "reviewed_by")
    return [_submission_out(s) for s in subs]


@router.post("/my/assignments/{int:sid}/submit", auth=auth)
def my_assignment_submit(request, sid: int, data: SubmitIn):
    _guard(request, "training.view")
    s = get_object_or_404(Submission, pk=sid, user=request.auth)
    if s.status == SubmissionStatus.APPROVED:
        raise HttpError(400, "Bu topshiriq allaqachon qabul qilingan.")
    if s.assignment.requires_proof and not s.files.exists():
        raise HttpError(400, "Avval rasm yoki video dalil yuklang.")
    return _submission_out(services.submit(s, data.text))


@router.post("/my/assignments/{int:sid}/files", auth=auth)
def my_assignment_file(request, sid: int, file: UploadedFile = File(...)):
    _guard(request, "training.view")
    s = get_object_or_404(Submission, pk=sid, user=request.auth)
    if s.status == SubmissionStatus.APPROVED:
        raise HttpError(400, "Qabul qilingan topshiriqqa fayl qo'shib bo'lmaydi.")
    _check_file(file, IMAGE_EXT | VIDEO_EXT | {"pdf"}, MAX_VIDEO_MB if _ext(file) in VIDEO_EXT else MAX_FILE_MB)
    SubmissionFile.objects.create(submission=s, file=file)
    return _submission_out(s)


@router.delete("/my/submission-files/{int:fid}", auth=auth)
def my_assignment_file_delete(request, fid: int):
    _guard(request, "training.view")
    f = get_object_or_404(SubmissionFile, pk=fid, submission__user=request.auth)
    if f.submission.status in (SubmissionStatus.APPROVED, SubmissionStatus.SUBMITTED):
        raise HttpError(400, "Tekshiruvdagi topshiriq faylini o'chirib bo'lmaydi.")
    f.delete()
    return {"ok": True}


def _standard_out(s: Standard, user: Optional[User] = None) -> dict:
    ext = s.file.name.lower().rsplit(".", 1)[-1] if s.file else ""
    out = {"id": s.pk, "title": s.title, "category": s.category, "body": s.body, "file": _url(s.file),
           "file_url": s.file_url, "file_view": media.of(s.file, s.file_url),
           "file_kind": "image" if ext in IMAGE_EXT else "video" if ext in VIDEO_EXT else ("file" if ext else None),
           "version": s.version, "responsible": _umini(s.responsible),
           "responsible_id": str(s.responsible_id) if s.responsible_id else None,
           "is_active": s.is_active, "updated_at": _dt(s.updated_at), **_audience(s)}
    if user is not None:
        ack = StandardAck.objects.filter(standard=s, user=user, version=s.version).first()
        out["acked_at"] = _dt(ack.acked_at) if ack else None
    return out


@router.get("/my/standards", auth=auth)
def my_standards(request):
    _guard(request, "training.view")
    return [_standard_out(s, request.auth) for s in services.my_standards(request.auth)]


@router.post("/my/standards/{int:sid}/ack", auth=auth)
def my_standard_ack(request, sid: int):
    _guard(request, "training.view")
    s = get_object_or_404(Standard, pk=sid, is_active=True)
    StandardAck.objects.get_or_create(standard=s, user=request.auth, version=s.version)
    return _standard_out(s, request.auth)


@router.get("/my/certificates/{int:eid}", auth=auth)
def my_certificate(request, eid: int):
    _guard(request, "training.view")
    e = get_object_or_404(Enrollment.objects.select_related("course", "user", "course__responsible"), pk=eid)
    if e.user_id != request.auth.pk and not (_can(request, "training.review") or _can(request, "training.manage")):
        raise HttpError(403, "Bu sertifikat sizniki emas.")
    if not e.certificate_no:
        raise HttpError(404, "Kurs hali tugatilmagan — sertifikat yo'q.")
    best = [a.score for a in QuizAttempt.objects.filter(user=e.user, quiz__course=e.course, passed=True)]
    return {"certificate_no": e.certificate_no, "title": services.conf(request.tenant)["certificate_title"],
            "user": e.user.full_name or e.user.phone, "course": e.course.title, "completed_at": _dt(e.completed_at),
            "score": max(best) if best else None, "restaurant": request.tenant.name,
            "responsible": e.course.responsible.full_name if e.course.responsible else None}


# ================================================================== BOSHQARUV: meta
@router.get("/meta", auth=auth)
def meta(request):
    _guard(request, "training.view")
    positions = []
    try:
        from modules.hr.models import Position
        positions = [{"id": p.id, "name": p.name} for p in Position.objects.all()]
    except Exception:
        pass
    users = [_umini(u) for u in services.staff_users()]
    cats = sorted({c for c in Course.objects.exclude(category="").values_list("category", flat=True)} |
                  {c for c in Standard.objects.exclude(category="").values_list("category", flat=True)})
    return {"roles": [{"code": r.code, "name": r.name} for r in Role.objects.exclude(code="owner")],
            "positions": positions, "users": users, "categories": cats, "settings": services.conf(request.tenant),
            "can": {"manage": _can(request, "training.manage"), "review": _can(request, "training.review") or _can(request, "training.manage")}}


# ================================================================== BOSHQARUV: kurslar
@router.get("/courses", auth=auth)
def list_courses(request, archived: bool = False):
    _guard(request, "training.manage")
    return [_course_out(c, stats=True) for c in Course.objects.filter(is_archived=archived).select_related("responsible")]


@router.post("/courses", auth=auth)
def create_course(request, data: CourseIn):
    _guard(request, "training.manage")
    c = Course(created_by=request.auth, sort_order=Course.objects.count())
    _apply(c, data)
    c.save()
    record(request, "create", c)
    n = services.sync_course(c, request.auth, request.tenant)
    return {**_course_out(c, stats=True), "assigned": n}


@router.get("/courses/{int:cid}", auth=auth)
def get_course(request, cid: int):
    _guard(request, "training.manage")
    c = get_object_or_404(Course, pk=cid)
    return {**_course_out(c, stats=True),
            "lessons": [_lesson_out(les) for les in c.lessons.prefetch_related("files")],
            "quizzes": [_quiz_out(q) for q in c.quizzes.all()]}


@router.put("/courses/{int:cid}", auth=auth)
def update_course(request, cid: int, data: CourseIn):
    _guard(request, "training.manage")
    c = get_object_or_404(Course, pk=cid)
    _apply(c, data)
    c.save()
    record(request, "update", c)
    n = services.sync_course(c, request.auth, request.tenant)
    return {**_course_out(c, stats=True), "assigned": n}


@router.delete("/courses/{int:cid}", auth=auth)
def delete_course(request, cid: int):
    """O'chirish = arxivga (natijalar saqlanadi)."""
    _guard(request, "training.manage")
    c = get_object_or_404(Course, pk=cid)
    c.is_archived = True
    c.save(update_fields=["is_archived", "updated_at"])
    record(request, "archive", c)
    return {"ok": True}


@router.post("/courses/{int:cid}/cover", auth=auth)
def upload_cover(request, cid: int, file: UploadedFile = File(...)):
    _guard(request, "training.manage")
    c = get_object_or_404(Course, pk=cid)
    _check_file(file, IMAGE_EXT, 10)
    c.cover = file
    c.save(update_fields=["cover", "updated_at"])
    return _course_out(c)


@router.post("/courses/{int:cid}/assign", auth=auth)
def assign_course(request, cid: int, data: AudienceIn):
    """Qo'shimcha xodimlarni biriktirish (auditoriyaga qo'shiladi) va hammani qayta sinxronlash."""
    _guard(request, "training.manage")
    c = get_object_or_404(Course, pk=cid)
    c.user_ids = sorted({*[str(x) for x in c.user_ids], *data.user_ids})
    c.roles = sorted({*c.roles, *data.roles})
    c.positions = sorted({*c.positions, *data.positions})
    c.everyone = c.everyone or data.everyone
    c.save()
    if not c.is_published:
        raise HttpError(400, "Kurs hali e'lon qilinmagan — avval «E'lon qilish»ni yoqing.")
    return {"assigned": services.sync_course(c, request.auth, request.tenant)}


# ---- darslar
@router.post("/courses/{int:cid}/lessons", auth=auth)
def create_lesson(request, cid: int, data: LessonIn):
    _guard(request, "training.manage")
    c = get_object_or_404(Course, pk=cid)
    les = Lesson.objects.create(course=c, sort_order=c.lessons.count(), **data.dict())
    record(request, "create", les)
    return _lesson_out(les)


@router.put("/lessons/{int:lid}", auth=auth)
def update_lesson(request, lid: int, data: LessonIn):
    _guard(request, "training.manage")
    les = get_object_or_404(Lesson, pk=lid)
    for k, v in data.dict().items():
        setattr(les, k, v)
    les.save()
    return _lesson_out(les)


@router.delete("/lessons/{int:lid}", auth=auth)
def delete_lesson(request, lid: int):
    _guard(request, "training.manage")
    les = get_object_or_404(Lesson, pk=lid)
    course, users = les.course, list(Enrollment.objects.filter(course=les.course).values_list("user_id", flat=True))
    record(request, "delete", les)
    les.delete()
    for uid in users:
        services.recompute(course, User(pk=uid))
    return {"ok": True}


@router.post("/courses/{int:cid}/lessons/order", auth=auth)
def order_lessons(request, cid: int, data: OrderIn):
    _guard(request, "training.manage")
    with transaction.atomic():
        for i, lid in enumerate(data.ids):
            Lesson.objects.filter(pk=lid, course_id=cid).update(sort_order=i)
    return {"ok": True}


@router.post("/lessons/{int:lid}/video", auth=auth)
def upload_video(request, lid: int, file: UploadedFile = File(...)):
    _guard(request, "training.manage")
    les = get_object_or_404(Lesson, pk=lid)
    _check_file(file, VIDEO_EXT, MAX_VIDEO_MB)
    les.video = file
    les.duration_seconds = 0
    les.save()
    return _lesson_out(les)


@router.delete("/lessons/{int:lid}/video", auth=auth)
def delete_video(request, lid: int):
    _guard(request, "training.manage")
    les = get_object_or_404(Lesson, pk=lid)
    les.video = ""
    les.video_url = ""
    les.duration_seconds = 0
    les.save()
    return _lesson_out(les)


@router.post("/lessons/{int:lid}/image", auth=auth)
def upload_lesson_image(request, lid: int, file: UploadedFile = File(...)):
    _guard(request, "training.manage")
    les = get_object_or_404(Lesson, pk=lid)
    _check_file(file, IMAGE_EXT, 10)
    les.image = file
    les.save()
    return _lesson_out(les)


@router.post("/lessons/{int:lid}/files", auth=auth)
def upload_lesson_file(request, lid: int, title: str = "", file: UploadedFile = File(...)):
    _guard(request, "training.manage")
    les = get_object_or_404(Lesson, pk=lid)
    _check_file(file, None, MAX_FILE_MB)
    LessonFile.objects.create(lesson=les, file=file, title=title or file.name, size_bytes=file.size or 0)
    return _lesson_out(les)


@router.post("/lessons/{int:lid}/links", auth=auth)
def add_lesson_link(request, lid: int, data: LinkIn):
    """Faylni yuklamasdan havola qo'shish (Google Drive, Dropbox, sayt…)."""
    _guard(request, "training.manage")
    les = get_object_or_404(Lesson, pk=lid)
    url = data.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HttpError(400, "Havola http:// yoki https:// bilan boshlanishi kerak.")
    LessonFile.objects.create(lesson=les, url=url, title=data.title.strip() or url)
    return _lesson_out(les)


@router.delete("/files/{int:fid}", auth=auth)
def delete_lesson_file(request, fid: int):
    _guard(request, "training.manage")
    get_object_or_404(LessonFile, pk=fid).delete()
    return {"ok": True}


# ---- testlar
@router.post("/courses/{int:cid}/quizzes", auth=auth)
def create_quiz(request, cid: int, data: QuizIn):
    _guard(request, "training.manage")
    c = get_object_or_404(Course, pk=cid)
    q = Quiz.objects.create(course=c, sort_order=c.quizzes.count(), **data.dict())
    return _quiz_out(q, with_questions=True, admin=True)


@router.get("/quizzes/{int:qid}", auth=auth)
def get_quiz(request, qid: int):
    _guard(request, "training.manage")
    return _quiz_out(get_object_or_404(Quiz, pk=qid), with_questions=True, admin=True)


@router.put("/quizzes/{int:qid}", auth=auth)
def update_quiz(request, qid: int, data: QuizIn):
    _guard(request, "training.manage")
    q = get_object_or_404(Quiz, pk=qid)
    for k, v in data.dict().items():
        setattr(q, k, v)
    q.save()
    return _quiz_out(q, with_questions=True, admin=True)


@router.delete("/quizzes/{int:qid}", auth=auth)
def delete_quiz(request, qid: int):
    _guard(request, "training.manage")
    get_object_or_404(Quiz, pk=qid).delete()
    return {"ok": True}


@router.put("/quizzes/{int:qid}/questions", auth=auth)
def save_questions(request, qid: int, data: QuestionsIn):
    """Savollar ro'yxatini to'liq saqlash (qo'shish/tahrirlash/o'chirish bir yo'la)."""
    _guard(request, "training.manage")
    q = get_object_or_404(Quiz, pk=qid)
    for i, x in enumerate(data.questions, 1):
        opts = [o for o in x.options if o.text.strip()]
        if len(opts) < 2:
            raise HttpError(400, f"{i}-savolda kamida 2 ta javob varianti bo'lsin.")
        if not x.correct or not set(x.correct) <= {o.id for o in opts}:
            raise HttpError(400, f"{i}-savolda to'g'ri javobni belgilang.")
    with transaction.atomic():
        keep = []
        for i, x in enumerate(data.questions):
            obj = Question.objects.filter(pk=x.id, quiz=q).first() if x.id else None
            obj = obj or Question(quiz=q)
            obj.text, obj.explanation, obj.sort_order = x.text, x.explanation, i
            obj.options = [{"id": o.id, "text": o.text} for o in x.options if o.text.strip()]
            obj.correct = x.correct
            obj.save()
            keep.append(obj.pk)
        q.questions.exclude(pk__in=keep).delete()
    return _quiz_out(q, with_questions=True, admin=True)


# ================================================================== topshiriqlar
def _assignment_out(a: Assignment) -> dict:
    subs = Submission.objects.filter(assignment=a)
    counts = {s: 0 for s in SubmissionStatus.values}
    for row in subs.values("status").annotate(n=Count("id")):
        counts[row["status"]] = row["n"]
    return {"id": a.pk, "title": a.title, "description": a.description, "media": _url(a.media), "media_url": a.media_url, "media_view": media.of(a.media, a.media_url),
            "media_is_video": bool(a.media) and a.media.name.lower().rsplit(".", 1)[-1] in VIDEO_EXT,
            "course_id": a.course_id, "due_at": _dt(a.due_at), "requires_proof": a.requires_proof,
            "responsible": _umini(a.responsible), "responsible_id": str(a.responsible_id) if a.responsible_id else None,
            "is_active": a.is_active, "created_at": _dt(a.created_at), **_audience(a),
            "counts": counts, "total": sum(counts.values())}


def _can_review(request, a: Assignment) -> bool:
    return _can(request, "training.review") or _can(request, "training.manage") or a.responsible_id == request.auth.pk


@router.get("/assignments", auth=auth)
def list_assignments(request):
    _guard(request, "training.view")
    qs = Assignment.objects.select_related("responsible")
    if not (_can(request, "training.review") or _can(request, "training.manage")):
        qs = qs.filter(responsible=request.auth)
    return [_assignment_out(a) for a in qs]


@router.post("/assignments", auth=auth)
def create_assignment(request, data: AssignmentIn):
    _guard(request, "training.manage")
    a = Assignment(created_by=request.auth)
    _apply(a, data)
    a.save()
    record(request, "create", a)
    n = services.sync_assignment(a, request.tenant)
    return {**_assignment_out(a), "assigned": n}


@router.put("/assignments/{int:aid}", auth=auth)
def update_assignment(request, aid: int, data: AssignmentIn):
    _guard(request, "training.manage")
    a = get_object_or_404(Assignment, pk=aid)
    _apply(a, data)
    a.save()
    services.sync_assignment(a, request.tenant)
    return _assignment_out(a)


@router.delete("/assignments/{int:aid}", auth=auth)
def delete_assignment(request, aid: int):
    _guard(request, "training.manage")
    a = get_object_or_404(Assignment, pk=aid)
    a.is_active = False
    a.save(update_fields=["is_active", "updated_at"])
    return {"ok": True}


@router.post("/assignments/{int:aid}/media", auth=auth)
def upload_assignment_media(request, aid: int, file: UploadedFile = File(...)):
    _guard(request, "training.manage")
    a = get_object_or_404(Assignment, pk=aid)
    _check_file(file, IMAGE_EXT | VIDEO_EXT | {"pdf"}, MAX_VIDEO_MB if _ext(file) in VIDEO_EXT else MAX_FILE_MB)
    a.media = file
    a.save()
    return _assignment_out(a)


@router.get("/assignments/{int:aid}/submissions", auth=auth)
def list_submissions(request, aid: int):
    _guard(request, "training.view")
    a = get_object_or_404(Assignment, pk=aid)
    if not _can_review(request, a):
        raise HttpError(403, "Siz bu topshiriqning mas'uli emassiz.")
    order = {SubmissionStatus.SUBMITTED: 0, SubmissionStatus.REJECTED: 1, SubmissionStatus.TODO: 2, SubmissionStatus.APPROVED: 3}
    subs = list(a.submissions.select_related("user", "reviewed_by", "assignment").prefetch_related("files"))
    subs.sort(key=lambda s: (order.get(s.status, 9), s.user.full_name))
    return [_submission_out(s, admin=True) for s in subs]


@router.post("/submissions/{int:sid}/review", auth=auth)
def review_submission(request, sid: int, data: ReviewIn):
    _guard(request, "training.view")
    s = get_object_or_404(Submission.objects.select_related("assignment", "user"), pk=sid)
    if not _can_review(request, s.assignment):
        raise HttpError(403, "Siz bu topshiriqning mas'uli emassiz.")
    if s.status != SubmissionStatus.SUBMITTED:
        raise HttpError(400, "Xodim hali topshirmagan — tekshiradigan narsa yo'q.")
    if not data.approve and not data.note.strip():
        raise HttpError(400, "Qaytarishda sababini yozing — xodim nimani tuzatishini bilsin.")
    return _submission_out(services.review(s, request.auth, data.approve, data.note, request.tenant), admin=True)


# ================================================================== standartlar
@router.get("/standards", auth=auth)
def list_standards(request):
    _guard(request, "training.manage")
    out = []
    for s in Standard.objects.select_related("responsible"):
        aud = services.audience_users(s)
        acked = set(StandardAck.objects.filter(standard=s, version=s.version).values_list("user_id", flat=True))
        out.append({**_standard_out(s), "audience": len(aud), "acked": sum(1 for u in aud if u.pk in acked)})
    return out


@router.post("/standards", auth=auth)
def create_standard(request, data: StandardIn):
    _guard(request, "training.manage")
    s = Standard(sort_order=Standard.objects.count())
    _apply(s, data)
    s.save()
    record(request, "create", s)
    return _standard_out(s)


@router.put("/standards/{int:sid}", auth=auth)
def update_standard(request, sid: int, data: StandardIn):
    _guard(request, "training.manage")
    s = get_object_or_404(Standard, pk=sid)
    _apply(s, data)
    s.save()
    return _standard_out(s)


@router.post("/standards/{int:sid}/new-version", auth=auth)
def standard_new_version(request, sid: int):
    """Qoida o'zgardi — hamma qaytadan tanishib chiqishi kerak."""
    _guard(request, "training.manage")
    s = get_object_or_404(Standard, pk=sid)
    s.version += 1
    s.save(update_fields=["version", "updated_at"])
    for u in services.audience_users(s):
        services.notify(request.tenant, u, f"📋 Standart yangilandi: <b>{s.title}</b> (v{s.version}). Tanishib chiqing.")
    record(request, "new_version", s)
    return _standard_out(s)


@router.delete("/standards/{int:sid}", auth=auth)
def delete_standard(request, sid: int):
    _guard(request, "training.manage")
    s = get_object_or_404(Standard, pk=sid)
    s.is_active = False
    s.save(update_fields=["is_active", "updated_at"])
    return {"ok": True}


@router.post("/standards/{int:sid}/file", auth=auth)
def upload_standard_file(request, sid: int, file: UploadedFile = File(...)):
    _guard(request, "training.manage")
    s = get_object_or_404(Standard, pk=sid)
    _check_file(file, IMAGE_EXT | VIDEO_EXT | {"pdf", "doc", "docx"}, MAX_VIDEO_MB if _ext(file) in VIDEO_EXT else MAX_FILE_MB)
    s.file = file
    s.save()
    return _standard_out(s)


@router.get("/standards/{int:sid}/acks", auth=auth)
def standard_acks(request, sid: int):
    _guard(request, "training.manage")
    s = get_object_or_404(Standard, pk=sid)
    acks = {a.user_id: a for a in StandardAck.objects.filter(standard=s, version=s.version)}
    return [{"user": _umini(u), "acked_at": _dt(acks[u.pk].acked_at) if u.pk in acks else None} for u in services.audience_users(s)]


# ================================================================== hisobot
def _report_guard(request):
    require_module(request, "training")
    if not (_can(request, "training.review") or _can(request, "training.manage")):
        raise HttpError(403, "Ruxsat yo'q: training.review")


@router.get("/report/summary", auth=auth)
def report_summary(request):
    _report_guard(request)
    rows = []
    names = dict(Role.objects.values_list("code", "name"))
    for u in services.staff_users():
        roles = services.user_roles(u)
        if roles <= {"owner"}:
            continue
        s = services.user_summary(u)
        rows.append({"user": _umini(u), "roles": [names.get(r, r) for r in sorted(roles)], **s, "last_activity": _dt(s["last_activity"])})
    ens = Enrollment.objects.filter(course__is_archived=False)
    total, done = ens.count(), ens.filter(status=EnrollmentStatus.COMPLETED).count()
    overdue = ens.exclude(status=EnrollmentStatus.COMPLETED).filter(due_at__lt=timezone.now()).count()
    scores = [r["avg_score"] for r in rows if r["avg_score"] is not None]
    review = Submission.objects.filter(status=SubmissionStatus.SUBMITTED, assignment__is_active=True).count()
    std_total = sum(r["standards_total"] for r in rows)
    std_acked = sum(r["standards_acked"] for r in rows)
    not_started = ens.filter(status=EnrollmentStatus.ASSIGNED).count()
    return {
        "kpis": {"completion": round(100 * done / total) if total else 0, "enrollments": total, "completed": done,
                 "overdue": overdue, "not_started": not_started, "avg_score": round(sum(scores) / len(scores)) if scores else None,
                 "to_review": review, "standards_percent": round(100 * std_acked / std_total) if std_total else None},
        "rows": rows,
    }


@router.get("/report/users/{uid}", auth=auth)
def report_user(request, uid: str):
    _report_guard(request)
    u = get_object_or_404(User, pk=uid)
    courses = []
    for e in Enrollment.objects.filter(user=u, course__is_archived=False).select_related("course"):
        prog = {p.lesson_id: p for p in LessonProgress.objects.filter(user=u, lesson__course=e.course)}
        lessons = [{"id": les.pk, "title": les.title, "has_video": les.has_video, "percent": prog[les.pk].percent if les.pk in prog else 0,
                    "done": bool(les.pk in prog and prog[les.pk].completed_at), "views": prog[les.pk].views if les.pk in prog else 0,
                    "watched_seconds": int(prog[les.pk].watched_seconds) if les.pk in prog else 0,
                    "duration_seconds": les.duration_seconds, "last_at": _dt(prog[les.pk].updated_at) if les.pk in prog else None}
                   for les in e.course.lessons.all()]
        quizzes = []
        for q in e.course.quizzes.all():
            at = list(QuizAttempt.objects.filter(quiz=q, user=u, finished_at__isnull=False))
            quizzes.append({"id": q.pk, "title": q.title, "attempts": len(at), "best": max((a.score for a in at), default=None),
                            "passed": any(a.passed for a in at)})
        courses.append({**_enrollment_card(e, u), "lessons": lessons, "quizzes": quizzes})
    subs = [_submission_out(s) for s in Submission.objects.filter(user=u, assignment__is_active=True).select_related("assignment")]
    stds = [_standard_out(s, u) for s in services.my_standards(u)]
    return {"user": _umini(u), "roles": sorted(services.user_roles(u)), "summary": services.user_summary(u),
            "courses": courses, "assignments": subs, "standards": stds}


@router.get("/report/courses/{int:cid}", auth=auth)
def report_course(request, cid: int):
    _report_guard(request)
    c = get_object_or_404(Course, pk=cid)
    lesson_ids = list(c.lessons.values_list("id", flat=True))
    rows = []
    for e in Enrollment.objects.filter(course=c).select_related("user"):
        done = LessonProgress.objects.filter(user=e.user, lesson_id__in=lesson_ids, completed_at__isnull=False).count()
        best = QuizAttempt.objects.filter(user=e.user, quiz__course=c, finished_at__isnull=False).order_by("-score").first()
        rows.append({"enrollment_id": e.pk, "user": _umini(e.user), "status": e.status, "progress": e.progress,
                     "lessons_done": done, "lessons_total": len(lesson_ids), "best_score": best.score if best else None,
                     "due_at": _dt(e.due_at), "is_overdue": e.is_overdue, "completed_at": _dt(e.completed_at),
                     "certificate_no": e.certificate_no or None})
    rows.sort(key=lambda r: ({"assigned": 0, "in_progress": 1, "completed": 2}[r["status"]], -int(r["is_overdue"])))
    return {"course": _course_out(c, stats=True), "rows": rows}


@router.get("/report/overdue", auth=auth)
def report_overdue(request):
    """Mas'ul uchun tezkor ro'yxat: muddati o'tgan kurslar va tekshiruvni kutayotgan topshiriqlar."""
    _report_guard(request)
    now = timezone.now()
    ens = Enrollment.objects.exclude(status=EnrollmentStatus.COMPLETED).filter(due_at__lt=now, course__is_archived=False).select_related("user", "course")
    subs = Submission.objects.filter(Q(status=SubmissionStatus.SUBMITTED)).select_related("user", "assignment")
    return {"courses": [{"user": _umini(e.user), "course": e.course.title, "course_id": e.course_id, "progress": e.progress,
                         "due_at": _dt(e.due_at)} for e in ens],
            "to_review": [{"id": s.pk, "user": _umini(s.user), "assignment": s.assignment.title, "assignment_id": s.assignment_id,
                           "submitted_at": _dt(s.submitted_at)} for s in subs]}
