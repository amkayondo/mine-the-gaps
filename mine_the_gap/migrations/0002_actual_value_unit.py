# Generated by Django 3.2.5 on 2021-11-30 16:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mine_the_gap', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='actual_value',
            name='unit',
            field=models.CharField(max_length=20, null=True),
        ),
    ]
