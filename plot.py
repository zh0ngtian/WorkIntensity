import os
import json
from datetime import datetime, timedelta
import webbrowser

import storage


def _build_active_block_record(seconds_list, block_duration, period_count, blocks_per_period):
    active_block_record = [[0 for _ in range(blocks_per_period)] for _ in range(period_count)]
    seconds_per_period = block_duration * blocks_per_period
    for seconds_since_midnight in seconds_list:
        period_index = seconds_since_midnight // seconds_per_period
        block_index = (seconds_since_midnight % seconds_per_period) // block_duration
        if 0 <= period_index < period_count and 0 <= block_index < blocks_per_period:
            active_block_record[period_index][block_index] = 1
    return active_block_record


def calculate_daily_work_hours(seconds_list):
    active_block_record = _build_active_block_record(seconds_list, block_duration=36, period_count=24, blocks_per_period=100)
    activities_per_hour = [sum(x) / 100.0 for x in active_block_record]
    return round(sum(activities_per_hour), 1)


def calculate_hourly_percent(seconds_list):
    active_block_record = _build_active_block_record(seconds_list, block_duration=36, period_count=24, blocks_per_period=100)
    return [int(sum(x)) for x in active_block_record]


def get_last_several_days_activities(num_days):
    start_of_last_several_days = datetime.now().date() - timedelta(days=num_days - 1)
    last_several_days_date = []
    last_several_days_activities_daily = []
    day_seconds_map = {}
    for i in range(num_days):
        current_date = start_of_last_several_days + timedelta(days=i)
        day_key = current_date.strftime("%Y-%m-%d")
        seconds_list = storage.get_activity_seconds_for_date(current_date)
        day_seconds_map[day_key] = seconds_list
        last_several_days_date.append(current_date.strftime("%m-%d"))
        last_several_days_activities_daily.append(calculate_daily_work_hours(seconds_list) if seconds_list else 0)
    return last_several_days_date, last_several_days_activities_daily, day_seconds_map


def plot_fig():
    week_number = 24
    today_date = datetime.today().date()

    num_days = (week_number - 1) * 7 + datetime.today().weekday() + 1
    last_several_days_data, last_several_days_activities_daily, day_seconds_map = get_last_several_days_activities(num_days)

    for i in range(num_days, week_number * 7):
        last_several_days_activities_daily.append(-1)

    start_date = datetime.now().date() - timedelta(days=num_days - 1)
    xlabels = []
    for i in range(week_number - 1):
        start_label = last_several_days_data[i * 7]
        end_label = last_several_days_data[i * 7 + 6]
        xlabels.append(f"{start_label} - {end_label}")
    xlabels.append(
        f'{last_several_days_data[(week_number - 1) * 7]} - {(datetime.today() + timedelta(7 - datetime.today().weekday() - 1)).strftime("%m-%d")}'
    )

    ylabels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    heatmap_data = []
    for week_index in range(week_number):
        for day_index in range(7):
            value = last_several_days_activities_daily[week_index * 7 + day_index]
            if value is None or value < 0:
                continue
            cell_date = start_date + timedelta(days=week_index * 7 + day_index)
            day_key = cell_date.strftime("%Y-%m-%d")
            hourly_percent = calculate_hourly_percent(day_seconds_map.get(day_key, []))
            heatmap_data.append(
                [week_index, day_index, value, hourly_percent, cell_date.strftime("%Y-%m-%d"), ylabels[cell_date.weekday()]]
            )

    trend_days = min(30, len(last_several_days_data))
    trend_labels = last_several_days_data[-trend_days:]
    trend_values = last_several_days_activities_daily[:num_days][-trend_days:]
    trend_dates = [(today_date - timedelta(days=trend_days - 1 - i)).strftime("%Y-%m-%d") for i in range(trend_days)]
    trend_weekdays = [ylabels[(today_date - timedelta(days=trend_days - 1 - i)).weekday()] for i in range(trend_days)]
    trend_max = max(trend_values, default=0)
    trend_y_max = max(9, int(trend_max) + 1)
    trend_total = round(sum(trend_values), 1)
    recorded_values = [value for value in last_several_days_activities_daily[:num_days] if value is not None and value >= 0]
    active_days_count = len([value for value in recorded_values if value > 0])
    average_daily_work = round(sum(recorded_values) / len(recorded_values), 1) if recorded_values else 0
    peak_daily_work = round(max(recorded_values), 1) if recorded_values else 0
    current_local_date_str = today_date.strftime("%Y-%m-%d")
    current_local_hour = datetime.now().hour

    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plot_template.html")
    with open(template_path, "r", encoding="utf-8") as template_file:
        html = template_file.read()

    replacements = {
        "__WEEK_NUMBER__": str(week_number),
        "__ACTIVE_DAYS_COUNT__": str(active_days_count),
        "__AVERAGE_DAILY_WORK__": str(average_daily_work),
        "__PEAK_DAILY_WORK__": str(peak_daily_work),
        "__TREND_DAYS__": str(trend_days),
        "__TREND_TOTAL__": str(trend_total),
        "__WEEK_RANGES_JSON__": json.dumps(xlabels, ensure_ascii=False),
        "__YLABELS_JSON__": json.dumps(ylabels, ensure_ascii=False),
        "__START_DATE_STR_JSON__": json.dumps(start_date.strftime("%Y-%m-%d"), ensure_ascii=False),
        "__CURRENT_LOCAL_DATE_STR_JSON__": json.dumps(current_local_date_str, ensure_ascii=False),
        "__CURRENT_LOCAL_HOUR__": str(current_local_hour),
        "__HEATMAP_DATA_JSON__": json.dumps(heatmap_data, ensure_ascii=False),
        "__TREND_LABELS_JSON__": json.dumps(trend_labels, ensure_ascii=False),
        "__TREND_VALUES_JSON__": json.dumps(trend_values, ensure_ascii=False),
        "__TREND_DATES_JSON__": json.dumps(trend_dates, ensure_ascii=False),
        "__TREND_WEEKDAYS_JSON__": json.dumps(trend_weekdays, ensure_ascii=False),
        "__TREND_Y_MAX__": str(trend_y_max),
    }
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, value)

    os.makedirs("log", exist_ok=True)
    html_path = os.path.abspath(os.path.join("log", "work_intensity.html"))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    webbrowser.open(f"file://{html_path}")


if __name__ == "__main__":
    plot_fig()
