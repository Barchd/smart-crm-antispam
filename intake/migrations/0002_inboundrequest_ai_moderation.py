from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("intake", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="inboundrequest",
            name="ai_toxicity",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="inboundrequest",
            name="ai_troll_probability",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="inboundrequest",
            name="ai_off_topic_probability",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="inboundrequest",
            name="ai_moderation_labels",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
