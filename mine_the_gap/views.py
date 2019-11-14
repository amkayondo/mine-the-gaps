from django.shortcuts import render
from io import TextIOWrapper
from django.contrib.gis.geos import MultiPolygon, Polygon, Point
from django.http import JsonResponse
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

import csv
import json

from mine_the_gap.forms import FileUploadForm
from mine_the_gap.models import Actual_data, Estimated_data, Region, Sensor, Filenames
from django.db.models import Max, Min
from mine_the_gap.region_estimators.region_estimator_factory import Region_estimator_factory

@ensure_csrf_cookie
def home_page(request):
    if request.method == 'POST':
        form = FileUploadForm(request.POST, request.FILES)
        if form.is_valid():
            handle_uploaded_files(request)
            filenames = Filenames.objects.first()
            if not filenames:
                filenames = Filenames()

            if form.cleaned_data.get("sensor_data_file"):
                filenames.sensor_data_file = form.cleaned_data.get("sensor_data_file")
            if form.cleaned_data.get("actual_data_file"):
                filenames.actual_data_file = form.cleaned_data.get("actual_data_file")
            if form.cleaned_data.get("region_data_file"):
                filenames.region_data_file = form.cleaned_data.get("region_data_file")
            if form.cleaned_data.get("estimated_data_file"):
                filenames.estimated_data_file = form.cleaned_data.get("estimated_data_file")
            filenames.save()

            return HttpResponseRedirect(request.path_info)

    context = { 'form': FileUploadForm(),
                'center': get_center_latlng(),
                'filepaths': Filenames.objects.all(),
                'timestamp_range': get_timestamp_list()}

    return render(request, 'index.html', context)


def get_sensor_fields(request):
    result = []

    # Check sensors exist
    first_sensor = Sensor.objects.first()

    if first_sensor:
        # Sensors exist so get field names from the Sensor model
        for field in Sensor._meta.get_fields():
            if not (field.many_to_one) and field.related_model is None:
                field_name = field.name

                if field_name == 'id' or field_name == 'geom':
                    continue
                elif field_name == 'extra_data':
                    result.extend(first_sensor.extra_data.keys())
                else:
                    result.append(field_name)

    #print(str(result))
    return JsonResponse(result, safe=False)

def get_actuals_at_timestamp(request, timestamp_idx):
    timestamps = get_timestamp_list()
    try:
        sensor_params = json.loads(request.body.decode("utf-8"))['selectors']
    except:
        sensor_params = []

    data = []


    try:
        timestamp_d = timestamps[timestamp_idx]
    except:
        return JsonResponse(data, safe=False)

    query_set = Actual_data.objects.filter(timestamp=timestamp_d)



    min_val = Actual_data.objects.aggregate(Min('value'))['value__min']
    max_val = Actual_data.objects.aggregate(Max('value'))['value__max']

    for row in query_set.iterator():
        #print('row value', row.value)
        if row.value:
            percentage_score = (row.value - min_val) / (max_val - min_val)
        else:
            percentage_score = None
        new_row = dict(row.join_sensor)

        new_row['ignore'] = False if select_sensor(new_row, sensor_params) else True

        new_row['percent_score'] = percentage_score
        data.append(new_row)

    return JsonResponse(data, safe=False)

def select_sensor(sensor, params):
    # [{"name": {"omit_sensors": ["Inverness"]}}]
    # [{"name": {"select_sensors": ["Inverness"]}}]
    for item in params:
        item_key = next(iter(item))
        if item_key == 'name':
            sensor_field = sensor['name']
        else:
            sensor_field = sensor['extra_data'][item_key]

        dict_item = item[item_key]
        if dict_item and 'select_sensors' in dict_item and sensor_field not in dict_item['select_sensors']:
            return False
        if dict_item and 'omit_sensors' in dict_item and sensor_field in dict_item['omit_sensors']:
            return False

    return True

def filter_sensors(sensors, params):
    # [{"name": {"omit_sensors": ["Inverness"]}}]
    # [{"pc": {"select_sensors": ["kdljdflja"]}}]

    for item in params:
        item_key = next(iter(item))
        dict_selector = item[item_key]
        omit_or_select = next(iter(dict_selector))
        include = True if omit_or_select == 'select_sensors' else False
        values = item[item_key][omit_or_select]

        if item_key == 'name':
            if include:
                sensors = sensors.filter(name__in=values)
            else:
                sensors = sensors.exclude(name__in=values)
        else:
            for value in values:
                if include:
                    sensors = sensors.filter(extra_data__contains={item_key: value})
                else:
                    sensors = sensors.exclude(extra_data__contains={item_key: value})

    return sensors


def get_estimates_at_timestamp(request, method_name, timestamp_idx):

    try:
        sensor_params = json.loads(request.body.decode("utf-8"))['selectors']
    except:
        sensor_params = []
    # print(json.dumps(sensor_params))

    data = []
    min_val = Actual_data.objects.aggregate(Min('value'))['value__min']
    max_val = Actual_data.objects.aggregate(Max('value'))['value__max']

    timestamps = get_timestamp_list()
    try:
        timestamp_d = timestamps[timestamp_idx]
    except:
        return JsonResponse(data, safe=False)


    if method_name == 'file':
        query_set = Estimated_data.objects.filter(timestamp=timestamp_d)
        for row in query_set.iterator():
            percentage_score = (row.value - min_val) / (max_val - min_val)
            new_row = dict(row.join_region)
            new_row['percent_score'] = percentage_score
            data.append(new_row)
    else:
        sensors = filter_sensors(Sensor.objects.all(), sensor_params)
        try:
            estimator = Region_estimator_factory.create_region_estimator(method_name, sensors)
        except Exception as err:
            print(err)
        else:
            result = estimator.get_all_region_estimations(timestamp_d)
            for row in result:
                #print('Row:', row['value'])
                if row['value']:
                    percentage_score = (row['value'] - min_val) / (max_val - min_val)
                else:
                    percentage_score = None
                row['percent_score'] = percentage_score
                data.append(row)

    return JsonResponse(data, safe=False)



def get_timestamp_list():
    query_set = Actual_data.objects.order_by('timestamp').values('timestamp').distinct()
    result = []

    for idx, item in enumerate(query_set):
        # e.g.: {'timestamp': datetime.date(2017, 1, 1)}
        result.append(item['timestamp'])

    return result

def get_center_latlng():
    x_average = 0
    y_average = 0
    found=False

    for idx, sensor in enumerate(Sensor.objects.all()):
        found = True
        x_average = x_average * (idx / (idx + 1)) + sensor.geom.coords[0] / (idx + 1)
        y_average = y_average * (idx / (idx + 1)) + sensor.geom.coords[1] / (idx + 1)

    if found:
        return json.dumps([str(y_average), str(x_average)])
    else:
        return ["54.2361", "-4.5481"]  # UK default


def handle_uploaded_files(request):

    try:
        filepath_sensor = request.FILES['sensor_data_file']
        filepath_actual = request.FILES['actual_data_file']
    except Exception as err:
        filepath_sensor, filepath_actual = False,False
        #print(err)
    else:
        Actual_data.objects.all().delete()
        Sensor.objects.all().delete()


        file = TextIOWrapper(filepath_sensor.file, encoding=request.encoding)
        reader = csv.reader(file)
        field_titles = next(reader, None)  # skip the headers

        #titles: ['long', 'lat', 'name', 'Postcode3', 'Address']

        for row in reader:
            try:
                extra_data = {}
                for idx, item in enumerate(field_titles[3:]):
                    extra_data[item] = row[idx+3]
                point_loc = Point(x=float(row[0]),y=float(row[1]))
                sensor, created = Sensor.objects.get_or_create(
                    geom = point_loc,
                    name =  row[2],
                    extra_data=extra_data)
                sensor.save()
            except Exception as err:
                #print(err)
                continue


        file = TextIOWrapper(filepath_actual.file, encoding=request.encoding)
        reader = csv.reader(file)
        field_titles = next(reader, None)  # skip the headers

        for row in reader:
            try:
                extra_data = {}
                for idx, item in enumerate(field_titles[4:]):
                    extra_data[item] = row[idx + 4]
                #print(str(extra_data))
                point_loc = Point(x=float(row[1]),y=float(row[2]))
                try:
                    fvalue = float(row[3])
                except:
                    fvalue = None
                actual = Actual_data(   timestamp=row[0],
                                        sensor = Sensor.objects.get(geom=point_loc),
                                        value = fvalue,
                                        extra_data = extra_data
                                        )
                actual.save()
            except Exception as err:
                #print(err)
                continue



    try:
        filepath_estimated = request.FILES['estimated_data_file']
        filepath_region = request.FILES['region_data_file']
    except Exception:
        filepath_estimated, filepath_region = False, False
    else:
        Estimated_data.objects.all().delete()
        Region.objects.all().delete()

        file = TextIOWrapper(filepath_region.file, encoding=request.encoding)
        reader = csv.reader(file)
        field_titles = next(reader, None)  # skip the headers
        #print('field titles:', field_titles)

        for row in reader:
            try:
                extra_data = {}
                for idx, item in enumerate(field_titles[2:]):
                    extra_data[item] = row[idx + 2]
                # Initialise polys
                multipoly_geo = MultiPolygon()
                poly = ()

                # Split the row
                poly_split = row[1].split(' ')[1:]

                # make first_point
                point_split = poly_split[0].strip().split(',')
                try:
                    first_point = (float(point_split[0]), float(point_split[1]))
                except:
                    continue

                start = True
                for point_str in poly_split:
                    point_split = point_str.strip().split(',')
                    point = (float(point_split[0]), float(point_split[1]))
                    poly = poly + (point,)
                    if start != True and point == first_point:
                        # Restart as enclosed circle found
                        # Make an enclosed circle
                        poly_geo = Polygon(poly)
                        multipoly_geo.append(poly_geo)
                        poly = ()
                        start = True
                    else:
                        start = False

                region = Region(region_id=str(row[0]),
                                geom=multipoly_geo,
                                extra_data=extra_data
                                )
                region.save()
            except Exception as err1:
                #print('Region file error. ', err1)
                #print('Region file error. Row: ', row[0])
                continue

        file = TextIOWrapper(filepath_estimated.file, encoding=request.encoding)
        reader = csv.reader(file)
        field_titles = next(reader, None)  # skip the headers
        #print('field titles:', field_titles)

        for row in reader:
            try:
                extra_data = {}
                for idx, item in enumerate(field_titles[3:]):
                    extra_data[item] = row[idx + 3]

                estimated = Estimated_data( timestamp=row[0],
                                            region=Region.objects.get(region_id=str(row[1])),
                                            value = float(row[2]),
                                            extra_data = extra_data
                                            )
                estimated.save()
            except Exception as err:
                #print(row)
                #print('Estimate file error: ', err, 'Region_ID:' + str(row[1]))
                continue





