"""
O'qitish moduli "miyasi": auditoriya, biriktirish, video nazorati, progress, test, hisobot.

Video nazorati (o'tkazib yuborib bo'lmaydi):
  brauzer har ~5 soniyada `beat` yuboradi: {position, duration, played}.
  Server `max_position` ni faqat haqiqiy o'tgan vaqt qadar oldinga suradi (played ≤ soat bo'yicha o'tgan vaqt + 3 s).
  Xodim videoni oxiriga surib qo'ysa — `max_position` o'zgarmaydi, foiz o'smaydi.
  Dars tugadi = max_position / duration ≥ sozlamadagi foiz (standart 90%).
"""
from __future__ import annotations

import json
import logging
import random
from datetime import timedelta
from pathlib import Path

from django.db import transaction
from django.utils import timezone

from core.events import emit
from core.models import User

from .models import (
    Assignment,
    Course,
    Enrollment,
    EnrollmentStatus,
    Lesson,
    LessonProgress,
    Quiz,
    QuizAttempt,
    Standard,
    StandardAck,
    Submission,
    SubmissionStatus,
)

log = logging.getLogger("training")

_DEFAULTS = {k: v.get("default") for k, v in json.loads(
    (Path(__file__).parent / "module.json").read_text(encoding="utf-8"))["settings_schema"]["properties"].items()}


def conf(tenant) -> dict:
    """Modul sozlamalari: tenant.settings["modules"]["training"] + standart qiymatlar."""
    saved = ((getattr(tenant, "settings", None) or {}).get("modules") or {}).get("training") or {}
    return {**_DEFAULTS, **saved}


# ------------------------------------------------------------------ auditoriya
def user_roles(user: User) -> set[str]:
    return set(user.memberships.filter(is_active=True).values_list("role__code", flat=True))


def user_position_id(user: User) -> int | None:
    try:
        from modules.hr.models import Employee
        return Employee.objects.filter(user=user).values_list("position_id", flat=True).first()
    except Exception:  # hr jadvali yo'q bo'lsa
        return None


def matches(obj, user: User, roles: set[str] | None = None, position_id: int | None = -1) -> bool:
    """Obyekt (kurs/topshiriq/standart) shu xodimga tegishlimi."""
    if str(user.pk) in [str(x) for x in (obj.user_ids or [])]:
        return True
    roles = user_roles(user) if roles is None else roles
    if roles and roles <= {"owner"}:          # egasi o'quvchi emas (aniq tanlanmagan bo'lsa)
        return False
    if obj.everyone:
        return bool(roles)
    if obj.roles and roles & set(obj.roles):
        return True
    if obj.positions:
        pid = user_position_id(user) if position_id == -1 else position_id
        if pid and pid in [int(x) for x in obj.positions]:
            return True
    return False


def staff_users():
    return User.objects.filter(is_active=True, memberships__is_active=True).distinct().order_by("full_name")


def audience_users(obj) -> list[User]:
    return [u for u in staff_users() if matches(obj, u)]


# ------------------------------------------------------------------ xabar
def notify(tenant, user: User, text: str) -> None:
    if not user.telegram_id or not conf(tenant).get("notify_telegram"):
        return
    try:
        from integrations.telegram import send_message
        send_message(user.telegram_id, text)
    except Exception:  # xabar ketmasa ham ish to'xtamasin
        log.exception("telegram xabar yuborilmadi")


# ------------------------------------------------------------------ biriktirish
def _due(course: Course):
    return timezone.now() + timedelta(days=course.due_days) if course.due_days else None


def enroll(course: Course, user: User, by: User | None = None, tenant=None) -> tuple[Enrollment, bool]:
    e, created = Enrollment.objects.get_or_create(course=course, user=user, defaults={"assigned_by": by, "due_at": _due(course)})
    if created and tenant is not None:
        due = f"\nMuddat: {e.due_at:%d.%m.%Y}" if e.due_at else ""
        notify(tenant, user, f"📚 Sizga yangi kurs biriktirildi: <b>{course.title}</b>{due}")
    return e, created


def sync_course(course: Course, by: User | None = None, tenant=None) -> int:
    """Auditoriyadagi barcha xodimlarga kursni biriktiradi. Yangi biriktirilganlar sonini qaytaradi."""
    if not course.is_published or course.is_archived:
        return 0
    n = 0
    for u in audience_users(course):
        _, created = enroll(course, u, by, tenant)
        n += created
    return n


def sync_assignment(a: Assignment, tenant=None) -> int:
    if not a.is_active:
        return 0
    n = 0
    for u in audience_users(a):
        _, created = Submission.objects.get_or_create(assignment=a, user=u)
        if created and tenant is not None:
            notify(tenant, u, f"📝 Yangi topshiriq: <b>{a.title}</b>")
        n += created
    return n


def sync_user(user: User, tenant=None) -> None:
    """Xodim o'z sahifasini ochganda: unga mos yangi kurs va topshiriqlar biriktiriladi."""
    roles, pid = user_roles(user), user_position_id(user)
    for c in Course.objects.filter(is_published=True, is_archived=False):
        if matches(c, user, roles, pid):
            enroll(c, user, None, tenant)
    for a in Assignment.objects.filter(is_active=True):
        if matches(a, user, roles, pid):
            Submission.objects.get_or_create(assignment=a, user=user)


def my_standards(user: User):
    roles, pid = user_roles(user), user_position_id(user)
    return [s for s in Standard.objects.filter(is_active=True) if matches(s, user, roles, pid)]


def standard_acked(s: Standard, user: User) -> bool:
    return StandardAck.objects.filter(standard=s, user=user, version=s.version).exists()


# ------------------------------------------------------------------ progress
def lesson_done_ids(user: User, course: Course) -> set[int]:
    return set(LessonProgress.objects.filter(user=user, lesson__course=course, completed_at__isnull=False)
               .values_list("lesson_id", flat=True))


def passed_quiz_ids(user: User, course: Course) -> set[int]:
    return set(QuizAttempt.objects.filter(user=user, quiz__course=course, passed=True).values_list("quiz_id", flat=True))


def lesson_locked(lesson: Lesson, done: set[int]) -> bool:
    """Darslar ketma-ket: oldingi dars tugamaguncha keyingisi yopiq."""
    for lid in Lesson.objects.filter(course=lesson.course).values_list("id", flat=True):
        if lid == lesson.pk:
            return False
        if lid not in done:
            return True
    return False


def recompute(course: Course, user: User) -> Enrollment | None:
    e = Enrollment.objects.filter(course=course, user=user).first()
    if e is None:
        return None
    lessons = list(course.lessons.values_list("id", flat=True))
    quizzes = list(course.quizzes.values_list("id", flat=True))
    done, passed = lesson_done_ids(user, course), passed_quiz_ids(user, course)
    total = len(lessons) + len(quizzes)
    ok = len(done & set(lessons)) + len(passed & set(quizzes))
    e.progress = round(100 * ok / total) if total else 0
    was_done = e.status == EnrollmentStatus.COMPLETED
    if total and ok >= total:
        e.status = EnrollmentStatus.COMPLETED
        if not e.completed_at:
            e.completed_at = timezone.now()
        if course.certificate and not e.certificate_no:
            e.certificate_no = f"{timezone.now():%y}-{course.pk:03d}-{e.pk:05d}"
    elif ok or LessonProgress.objects.filter(user=user, lesson__course=course).exists():
        e.status = EnrollmentStatus.IN_PROGRESS
        e.started_at = e.started_at or timezone.now()
    e.save()
    if e.status == EnrollmentStatus.COMPLETED and not was_done:
        emit("training.course_completed", {"course_id": course.pk, "user_id": str(user.pk)})
    return e


def open_lesson(user: User, lesson: Lesson) -> LessonProgress:
    p, _ = LessonProgress.objects.get_or_create(user=user, lesson=lesson)
    p.views += 1
    p.save(update_fields=["views", "updated_at"])
    Enrollment.objects.filter(course=lesson.course, user=user).update(last_lesson=lesson)
    recompute(lesson.course, user)
    return p


def beat(user: User, lesson: Lesson, *, position: float, duration: float, played: float, tenant=None) -> LessonProgress:
    """Video yurak urishi. Oldinga sakrash hisobga olinmaydi."""
    cfg = conf(tenant)
    now = timezone.now()
    with transaction.atomic():
        p, _ = LessonProgress.objects.select_for_update().get_or_create(user=user, lesson=lesson)
        elapsed = (now - p.last_beat_at).total_seconds() if p.last_beat_at else 15.0
        allowed = max(0.0, min(float(played), elapsed + 3.0, 60.0))
        if lesson.video_mode == "time":
            # Drive/Vimeo: brauzer videoni "ko'rmaydi" — sahifada o'tkazilgan vaqt, davomiylikni admin yozadi
            p.duration = float(lesson.duration_seconds or 60)
        elif duration and duration > 0:
            p.duration = float(duration)
            if not lesson.duration_seconds:
                Lesson.objects.filter(pk=lesson.pk).update(duration_seconds=int(duration))
        position = max(0.0, float(position))
        # yangi nuqta = oldingi eng uzoq nuqta + haqiqatda ko'rilgan vaqt (undan uzoqqa sakrash hisoblanmaydi)
        if position > p.max_position:
            p.max_position = min(position, p.max_position + allowed + 2.0)
        p.watched_seconds += allowed
        p.last_position = position
        p.last_beat_at = now
        if p.duration:
            p.max_position = min(p.max_position, p.duration)
            # oxirgi 2 soniya (titr) ko'rilmasa ham 100% deymiz
            p.percent = min(100, round(100 * min(1.0, (p.max_position + 2.0) / p.duration)))
        if p.percent >= int(cfg["min_watch_percent"]) and not p.completed_at:
            p.completed_at = now
        p.save()
    recompute(lesson.course, user)
    return p


def complete_text_lesson(user: User, lesson: Lesson) -> LessonProgress:
    p, _ = LessonProgress.objects.get_or_create(user=user, lesson=lesson)
    if not p.completed_at:
        p.completed_at = timezone.now()
        p.percent = 100
        p.save()
    recompute(lesson.course, user)
    return p


# ------------------------------------------------------------------ testlar
def attempts_left(quiz: Quiz, user: User) -> int | None:
    if not quiz.max_attempts:
        return None
    used = QuizAttempt.objects.filter(quiz=quiz, user=user, finished_at__isnull=False).count()
    return max(0, quiz.max_attempts - used)


def start_attempt(quiz: Quiz, user: User) -> QuizAttempt:
    ids = list(quiz.questions.values_list("id", flat=True))
    if quiz.shuffle:
        random.shuffle(ids)
    return QuizAttempt.objects.create(quiz=quiz, user=user, question_ids=ids, total=len(ids))


def grade(attempt: QuizAttempt, answers: dict) -> QuizAttempt:
    questions = {q.pk: q for q in attempt.quiz.questions.all()}
    late = False
    if attempt.quiz.time_limit_seconds:
        late = (timezone.now() - attempt.started_at).total_seconds() > attempt.quiz.time_limit_seconds + 15
    correct = 0
    clean: dict[str, list[str]] = {}
    for qid in attempt.question_ids:
        q = questions.get(qid)
        if q is None:
            continue
        given = sorted(str(x) for x in (answers.get(str(qid)) or answers.get(qid) or []))
        clean[str(qid)] = given
        if not late and given and given == sorted(str(x) for x in q.correct):
            correct += 1
    attempt.answers = clean
    attempt.correct_count = correct
    attempt.total = len(attempt.question_ids)
    attempt.score = round(100 * correct / attempt.total) if attempt.total else 0
    attempt.passed = attempt.score >= attempt.quiz.effective_pass_score
    attempt.finished_at = timezone.now()
    attempt.save()
    recompute(attempt.quiz.course, attempt.user)
    return attempt


# ------------------------------------------------------------------ topshiriq
def submit(sub: Submission, text: str) -> Submission:
    sub.text = text
    sub.status = SubmissionStatus.SUBMITTED
    sub.submitted_at = timezone.now()
    sub.attempts += 1
    sub.save()
    emit("training.assignment_submitted", {"submission_id": sub.pk, "assignment_id": sub.assignment_id})
    return sub


def review(sub: Submission, by: User, approve: bool, note: str = "", tenant=None) -> Submission:
    sub.status = SubmissionStatus.APPROVED if approve else SubmissionStatus.REJECTED
    sub.reviewed_by = by
    sub.reviewed_at = timezone.now()
    sub.review_note = note
    sub.save()
    msg = "✅ Topshiriq qabul qilindi" if approve else "↩️ Topshiriq qaytarildi"
    notify(tenant, sub.user, f"{msg}: <b>{sub.assignment.title}</b>" + (f"\n{note}" if note else ""))
    return sub


# ------------------------------------------------------------------ hisobot
def user_summary(user: User) -> dict:
    ens = list(Enrollment.objects.filter(user=user, course__is_archived=False).select_related("course"))
    lesson_ids = Lesson.objects.filter(course__in=[e.course for e in ens]).values_list("id", flat=True)
    quiz_ids = Quiz.objects.filter(course__in=[e.course for e in ens]).values_list("id", flat=True)
    lp = LessonProgress.objects.filter(user=user, lesson_id__in=list(lesson_ids))
    attempts = QuizAttempt.objects.filter(user=user, quiz_id__in=list(quiz_ids), finished_at__isnull=False)
    passed = set(attempts.filter(passed=True).values_list("quiz_id", flat=True))
    best: dict[int, int] = {}
    for a in attempts:
        best[a.quiz_id] = max(best.get(a.quiz_id, 0), a.score)
    subs = Submission.objects.filter(user=user, assignment__is_active=True)
    stds = my_standards(user)
    acked = sum(1 for s in stds if standard_acked(s, user))
    videos_total = Lesson.objects.filter(id__in=list(lesson_ids)).exclude(video="", video_url="").count()
    return {
        "courses_total": len(ens),
        "courses_done": sum(1 for e in ens if e.status == EnrollmentStatus.COMPLETED),
        "courses_overdue": sum(1 for e in ens if e.is_overdue),
        "lessons_total": len(lesson_ids),
        "lessons_done": lp.filter(completed_at__isnull=False).count(),
        "videos_total": videos_total,
        "videos_watched": lp.filter(completed_at__isnull=False).exclude(lesson__video="", lesson__video_url="").count(),
        "watch_seconds": int(sum(p.watched_seconds for p in lp)),
        "quizzes_total": len(quiz_ids),
        "quizzes_passed": len(passed),
        "avg_score": round(sum(best.values()) / len(best)) if best else None,
        "assignments_total": subs.count(),
        "assignments_open": subs.filter(status__in=[SubmissionStatus.TODO, SubmissionStatus.REJECTED]).count(),
        "assignments_review": subs.filter(status=SubmissionStatus.SUBMITTED).count(),
        "assignments_done": subs.filter(status=SubmissionStatus.APPROVED).count(),
        "standards_total": len(stds),
        "standards_acked": acked,
        "progress": round(sum(e.progress for e in ens) / len(ens)) if ens else 0,
        "last_activity": lp.order_by("-updated_at").values_list("updated_at", flat=True).first(),
    }
