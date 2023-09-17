import os
import re
import time
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np

# 定义正则表达式模式，用于匹配时间戳
timestamp_pattern = r"\[(\d{2}:\d{2}:\d{2})\]"


# 读取日志文件并解析时间戳
def parse_log_file(file_path):
    active_block_record = [[0 for _ in range(100)] for _ in range(48)]  # 初始化每个统计周期的活跃块数列表
    block_duration = 18  # 每个统计块的时长
    blocks_per_period = 100  # 每个统计周期的块数
    time_format = "%H:%M:%S"  # 时间戳的格式

    with open(file_path, "r") as file:
        for line in file:
            match = re.search(timestamp_pattern, line)
            if match:
                timestamp_str = match.group(1)
                timestamp = datetime.strptime(timestamp_str, time_format)
                # 计算时间戳距离当天零点的秒数
                seconds_since_midnight = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
                # 计算所属统计周期的索引
                period_index = seconds_since_midnight // (block_duration * blocks_per_period)
                block_index = seconds_since_midnight % (block_duration * blocks_per_period) // block_duration
                active_block_record[period_index][block_index] = 1

    activities_per_hour = [sum(x) for x in active_block_record]
    return activities_per_hour


# 绘制柱状图
def do_plot(today_activities_per_hour, last_week_date, last_week_activities_daily):
    per_hour_labels = [
        "00:00-00:30",
        "00:30-01:00",
        "01:00-01:30",
        "01:30-02:00",
        "02:00-02:30",
        "02:30-03:00",
        "03:00-03:30",
        "03:30-04:00",
        "04:00-04:30",
        "04:30-05:00",
        "05:00-05:30",
        "05:30-06:00",
        "06:00-06:30",
        "06:30-07:00",
        "07:00-07:30",
        "07:30-08:00",
        "08:00-08:30",
        "08:30-09:00",
        "09:00-09:30",
        "09:30-10:00",
        "10:00-10:30",
        "10:30-11:00",
        "11:00-11:30",
        "11:30-12:00",
        "12:00-12:30",
        "12:30-13:00",
        "13:00-13:30",
        "13:30-14:00",
        "14:00-14:30",
        "14:30-15:00",
        "15:00-15:30",
        "15:30-16:00",
        "16:00-16:30",
        "16:30-17:00",
        "17:00-17:30",
        "17:30-18:00",
        "18:00-18:30",
        "18:30-19:00",
        "19:00-19:30",
        "19:30-20:00",
        "20:00-20:30",
        "20:30-21:00",
        "21:00-21:30",
        "21:30-22:00",
        "22:00-22:30",
        "22:30-23:00",
        "23:00-23:30",
        "23:30-00:00",
    ]

    # only show work time: 10:00 - 22:00
    per_hour_labels = per_hour_labels[20:44]
    today_activities_per_hour = today_activities_per_hour[20:44]

    # 创建一个 matplotlib 图形对象，并分成两个子图
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # 绘制折线图
    ax1.set_title("Last Week Work Intensity")
    ax1.plot(last_week_date, last_week_activities_daily, marker="o", linestyle="-")
    ax1.set_xticks(range(len(last_week_date)))
    ax1.set_yticks(range(0, 101, 10))
    ax1.set_ylim(0, 100)

    # 获取纵轴刻度值并添加虚水平线
    yticks = ax1.get_yticks()
    for ytick in yticks:
        ax1.axhline(y=ytick, color="gray", linestyle="--", alpha=0.3)

    # 绘制柱状图
    ax2.set_title("Today Work Intensity")
    ax2.bar(range(len(today_activities_per_hour)), today_activities_per_hour, tick_label=per_hour_labels)
    ax2.set_xticks(range(len(today_activities_per_hour)))
    ax2.set_xticklabels(per_hour_labels, rotation=90)
    ax2.set_yticks(range(0, 101, 10))
    ax2.set_ylim(0, 100)

    # 获取纵轴刻度值并添加虚水平线
    yticks = ax2.get_yticks()
    for ytick in yticks:
        ax2.axhline(y=ytick, color="gray", linestyle="--", alpha=0.3)

    # 调整子图之间的间距
    plt.tight_layout()

    # 显示图形
    plt.show()


def get_last_week_activities():
    today = datetime.now()
    start_of_last_week = today - timedelta(days=7)

    last_week_date = []
    last_week_activities_daily = []
    for i in range(7):
        date = start_of_last_week + timedelta(days=i)

        last_week_date.append(date.strftime("%m-%d"))

        log_file_path = f'log/{date.strftime("%Y-%m-%d")}.log'
        if os.path.exists(log_file_path):
            activities_per_hour = parse_log_file(log_file_path)
            last_week_activities_daily.append(np.sum(activities_per_hour) / 24)
        else:
            last_week_activities_daily.append(0)

    return last_week_date, last_week_activities_daily


def plot_fig():
    today_log_file_path = f'log/{time.strftime("%Y-%m-%d")}.log'
    today_activities_per_hour = parse_log_file(today_log_file_path)

    last_week_date, last_week_activities_daily = get_last_week_activities()

    do_plot(today_activities_per_hour, last_week_date, last_week_activities_daily)


if __name__ == "__main__":
    plot_fig()
