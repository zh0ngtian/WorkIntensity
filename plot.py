import os
import re
import time
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import pickle


plt.rcParams["font.family"] = ["PingFang HK"]


timestamp_pattern = r"\[(\d{2}:\d{2}:\d{2})\]"


def parse_log_file(file_path):
    active_block_record = [[0 for _ in range(100)] for _ in range(24)]  # 初始化每个统计周期的活跃块数列表
    block_duration = 36  # 每个统计块的时长，单位为秒
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

    activities_per_hour = [sum(x) / 100.0 for x in active_block_record]
    work_intensity_daily = round(sum(activities_per_hour), 1)
    return work_intensity_daily


def plot_bar_fig(today_activities_per_hour, ax):
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

    # only show work time: 10:00 - 12:00, 14:00 - 18:00, 19:00 - 21:30
    work_per_hour_labels = per_hour_labels[20:24] + per_hour_labels[28:36] + per_hour_labels[38:43]
    work_today_activities_per_hour = (
        today_activities_per_hour[20:24] + today_activities_per_hour[28:36] + today_activities_per_hour[38:43]
    )

    # 绘制柱状图
    ax.set_title("Today Work Intensity")
    ax.bar(range(len(work_today_activities_per_hour)), work_today_activities_per_hour, tick_label=work_per_hour_labels)
    ax.set_xticks(range(len(work_today_activities_per_hour)))
    ax.set_xticklabels(work_per_hour_labels, rotation=90)
    ax.set_yticks(range(0, 101, 10))
    ax.set_ylim(0, 100)

    # 获取纵轴刻度值并添加虚水平线
    yticks = ax.get_yticks()
    for ytick in yticks:
        ax.axhline(y=ytick, color="gray", linestyle="--", alpha=0.3)


def plot_grid_fig(week_number, last_several_days_data_daily, xlabels, ax):
    # 定义颜色映射为绿色，根据数值大小分为 5 个档次
    cmap = plt.get_cmap("Greens")

    # 创建一个网格
    grid = np.array(last_several_days_data_daily).reshape(week_number, 7).T

    # 绘制每个格子
    for i in range(7):
        for j in range(week_number):
            value = grid[i, j]
            color = cmap(value / 9)  # 根据数值映射颜色
            ax.add_patch(plt.Rectangle((j, -i), 1, 1, fc=color, ec="black"))
            ax.annotate(
                str(value) + "h" if value > 0 else "",
                (j + 0.5, -i + 0.5),
                color="black",
                fontsize=10,
                ha="center",
                va="center",
            )

    # 隐藏边框
    for spine in ax.spines.values():
        spine.set_visible(False)

    # 隐藏刻度线
    ax.tick_params(axis="both", which="both", length=0)

    # 隐藏坐标轴标签
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    # 设置坐标轴比例和范围保证正方形
    ax.set_xlim(-0.5, week_number + 0.5)
    ax.set_ylim(-6, 2)
    ax.set_aspect("equal")

    # 添加横轴和纵轴的标注文字
    ylabels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    for i in range(week_number):
        ax.text(i + 0.5, 1.8, xlabels[i], ha="center", va="center", fontsize=10, rotation=270)
    for j in range(7):
        ax.text(-0.3, -j + 0.5, ylabels[j], ha="center", va="center", fontsize=10)


def get_last_several_days_activities(num_days):
    today = datetime.now()
    start_of_last_several_days = today - timedelta(days=num_days - 1)

    cache_file_path = os.path.join("log/work_intensity_cache.pkl")
    if os.path.exists(cache_file_path):
        with open(cache_file_path, "rb") as cache_file:
            cache = pickle.load(cache_file)
    else:
        cache = {}

    last_several_days_date = []
    last_several_days_activities_daily = []
    for i in range(num_days):
        date = start_of_last_several_days + timedelta(days=i)

        last_several_days_date.append(date.strftime("%m-%d"))

        log_file_path = f'log/{date.strftime("%Y-%m-%d")}.log'
        if os.path.exists(log_file_path):
            if date == today:
                work_intensity_daily = parse_log_file(log_file_path)
            else:
                if log_file_path not in cache:
                    cache[log_file_path] = parse_log_file(log_file_path)
                work_intensity_daily = cache[log_file_path]
            last_several_days_activities_daily.append(work_intensity_daily)
        else:
            last_several_days_activities_daily.append(0)

    # 将结果存入缓存
    with open(cache_file_path, "wb") as cache_file:
        pickle.dump(cache, cache_file)

    return last_several_days_date, last_several_days_activities_daily


def plot_fig():
    week_number = 24

    num_days = (week_number - 1) * 7 + datetime.today().weekday() + 1
    last_several_days_data, last_several_days_activities_daily = get_last_several_days_activities(num_days)

    for i in range(num_days, week_number * 7):
        last_several_days_activities_daily.append(-1)
    xlabels = []
    for i in range(week_number - 1):
        start_date = last_several_days_data[i * 7]
        end_date = last_several_days_data[i * 7 + 6]
        xlabels.append(f"{start_date} - {end_date}")
    xlabels.append(
        f'{last_several_days_data[(week_number - 1) * 7]} - {(datetime.today() + timedelta(7 - datetime.today().weekday() - 1)).strftime("%m-%d")}'
    )

    _, ax = plt.subplots(figsize=(20, 7))
    plot_grid_fig(week_number, last_several_days_activities_daily, xlabels, ax)

    # 显示图形
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    parse_log_file("log/2025-07-05.log")
