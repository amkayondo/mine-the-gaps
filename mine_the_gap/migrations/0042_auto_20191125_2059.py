# Generated by Django 2.0.13 on 2019-11-25 20:59

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('mine_the_gap', '0041_auto_20191124_0748'),
    ]

    operations = [
        migrations.RenameField(
            model_name='filenames',
            old_name='region_data_filename',
            new_name='region_metadata_filename',
        ),
        migrations.RenameField(
            model_name='filenames',
            old_name='sensor_data_filename',
            new_name='sensor_metadata_filename',
        ),
    ]
