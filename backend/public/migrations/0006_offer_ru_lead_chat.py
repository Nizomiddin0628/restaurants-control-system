from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("public", "0005_chat_session_ai_key")]

    operations = [
        migrations.AddField(model_name="siteoffer", name="lead_chat", field=models.CharField(blank=True, default="", help_text="Arizalar yuboriladigan Telegram chat ID (botga /id yozing)", max_length=40)),
        migrations.AddField(model_name="siteoffer", name="price_note_ru", field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(model_name="siteoffer", name="setup_note_ru", field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddField(model_name="siteoffer", name="includes_ru", field=models.JSONField(blank=True, default=list)),
    ]
