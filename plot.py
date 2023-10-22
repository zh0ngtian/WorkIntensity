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


def plot_line_fig(last_several_days_date, last_several_days_activities_daily, ax):
    # 绘制折线图
    ax.set_title("Last Week Work Intensity")
    ax.plot(last_several_days_date, last_several_days_activities_daily, marker="o", linestyle="-")
    ax.set_xticks(range(len(last_several_days_date)))
    ax.set_yticks(range(0, 101, 10))
    ax.set_ylim(0, 100)

    # 获取纵轴刻度值并添加虚水平线
    yticks = ax.get_yticks()
    for ytick in yticks:
        ax.axhline(y=ytick, color="gray", linestyle="--", alpha=0.3)


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


def plot_grid_fig(last_several_days_data_daily, ylabels, ax):
    # 定义颜色映射为绿色，根据数值大小分为5个档次
    cmap = plt.get_cmap("Greens")

    # 创建一个4x7的网格
    grid = np.array(last_several_days_data_daily).reshape(4, 7)

    # 绘制每个格子
    for i in range(4):
        for j in range(7):
            value = grid[i, j]
            color = cmap(value / 100)  # 根据数值映射颜色
            ax.add_patch(plt.Rectangle((j, -i), 1, 1, fc=color, ec="black"))
            ax.annotate(
                str(value) + "%" if value > 0 else "",
                (j + 0.5, -i + 0.5),
                color="black",
                fontsize=10,
                ha="center",
                va="center",
            )

    # 设置坐标轴标签
    ax.set_xticks(np.arange(8))
    ax.set_yticks(np.arange(-3, 0))
    ax.set_xticklabels([])
    ax.set_yticklabels([])

    # 添加横轴和纵轴的标注文字
    xlabels = ["Mon.", "Tue.", "Wed.", "Thu.", "Fri.", "Sat.", "Sun."]
    for i in range(4):
        ax.text(-0.5, -i + 0.5, ylabels[i], ha="center", va="center", fontsize=10)
    for j in range(7):
        ax.text(j + 0.5, -3.2, xlabels[j], ha="center", va="center", fontsize=10)

    # 设置标题
    ax.set_title("Last Month Work Intensity")


def get_last_several_days_activities(num_days):
    today = datetime.now()
    start_of_last_several_days = today - timedelta(days=num_days - 1)

    last_several_days_date = []
    last_several_days_activities_daily = []
    for i in range(num_days):
        date = start_of_last_several_days + timedelta(days=i)

        last_several_days_date.append(date.strftime("%m-%d"))

        log_file_path = f'log/{date.strftime("%Y-%m-%d")}.log'
        if os.path.exists(log_file_path):
            activities_per_hour = parse_log_file(log_file_path)
            last_several_days_activities_daily.append(
                round(np.sum(activities_per_hour) / 17)
            )  # standard work time is 9 hours
        else:
            last_several_days_activities_daily.append(0)

    return last_several_days_date, last_several_days_activities_daily


def plot_fig(today_log_file_path=None):
    if today_log_file_path == None:
        today_log_file_path = f'log/{time.strftime("%Y-%m-%d")}.log'
    today_activities_per_hour = parse_log_file(today_log_file_path)

    num_days = 21 + datetime.today().weekday() + 1
    last_several_days_data, last_several_days_activities_daily = get_last_several_days_activities(num_days)

    for i in range(num_days, 28):
        last_several_days_activities_daily.append(-1)
    ylabels = [
        f"{last_several_days_data[0]} - {last_several_days_data[6]}",
        f"{last_several_days_data[7]} - {last_several_days_data[13]}",
        f"{last_several_days_data[14]} - {last_several_days_data[20]}",
        f'{last_several_days_data[21]} - {(datetime.today() + timedelta(7 - datetime.today().weekday() - 1)).strftime("%m-%d")}',
    ]

    _, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 5))
    plot_grid_fig(last_several_days_activities_daily, ylabels, ax1)
    plot_bar_fig(today_activities_per_hour, ax2)

    # 显示图形
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    plot_fig()

    # data = [
    #     45,
    #     60,
    #     30,
    #     75,
    #     90,
    #     20,
    #     85,
    #     10,
    #     55,
    #     70,
    #     40,
    #     5,
    #     95,
    #     50,
    #     65,
    #     15,
    #     80,
    #     35,
    #     25,
    #     100,
    #     72,
    #     88,
    #     42,
    #     68,
    #     52,
    #     62,
    #     8,
    #     110,
    # ]
    # plot_month_data(data)
