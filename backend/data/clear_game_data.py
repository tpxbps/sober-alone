"""
清空游戏数据脚本
清空 game_records、player_states、game_sessions 表的数据
"""

import sqlite3
import os

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "game_data.db")


def clear_game_data():
    """清空游戏相关表的数据"""

    if not os.path.exists(DB_PATH):
        print(f"数据库文件不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        # 禁用外键约束检查（便于删除）
        cursor.execute("PRAGMA foreign_keys = OFF;")

        # 清空各表数据（按依赖关系顺序）
        tables = ["game_records", "player_states", "game_sessions"]

        for table in tables:
            cursor.execute(f"DELETE FROM {table};")
            deleted = cursor.rowcount
            print(f"已清空表: {table} (删除 {deleted} 条记录)")

        conn.commit()
        print("\n所有游戏数据已清空!")

        # 重置自增ID（可选，sqlite_sequence 可能不存在）
        try:
            for table in tables:
                cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}';")
        except sqlite3.Error:
            pass  # sqlite_sequence 表不存在则忽略

    except sqlite3.Error as e:
        conn.rollback()
        print(f"操作失败: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    confirm = input("确定要清空所有游戏数据吗? (输入 yes 确认): ")
    if confirm.lower() == "yes":
        clear_game_data()
    else:
        print("已取消操作")
