from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("bot", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="botsettings",
            name="customer_prompt",
            field=models.TextField(
                blank=True,
                help_text="Дополнительные инструкции для AI-черновиков клиентского Telegram-бота.",
                max_length=4000,
            ),
        ),
    ]
