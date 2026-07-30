# Generated manually for OpenAI model placeholder refresh.

from django.db import migrations, models


def update_old_defaults(apps, schema_editor):
    AISettings = apps.get_model("ai", "AISettings")
    AISettings.objects.filter(openai_model="gpt-4.1-mini").update(openai_model="gpt-5.6-sol")
    AISettings.objects.filter(openai_transcription_model="whisper-1").update(openai_transcription_model="gpt-transcribe")


def restore_old_defaults(apps, schema_editor):
    AISettings = apps.get_model("ai", "AISettings")
    AISettings.objects.filter(openai_model="gpt-5.6-sol").update(openai_model="gpt-4.1-mini")
    AISettings.objects.filter(openai_transcription_model="gpt-transcribe").update(openai_transcription_model="whisper-1")


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0002_aisettings_openai_transcription_model"),
    ]

    operations = [
        migrations.AlterField(
            model_name="aisettings",
            name="openai_model",
            field=models.CharField(default="gpt-5.6-sol", max_length=120),
        ),
        migrations.AlterField(
            model_name="aisettings",
            name="openai_transcription_model",
            field=models.CharField(default="gpt-transcribe", max_length=120),
        ),
        migrations.RunPython(update_old_defaults, reverse_code=restore_old_defaults),
    ]
