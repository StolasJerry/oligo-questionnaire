
import streamlit as st
import pandas as pd
import sqlite3
import json
from datetime import datetime
from pathlib import Path

try:
    APP_DIR = Path(__file__).parent
except NameError:
    APP_DIR = Path.cwd()

DB_PATH = APP_DIR / "questionnaire_data.db"
CONFIG_PATH = APP_DIR / "questionnaire_config.json"

def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS responses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submit_time TEXT NOT NULL,
        personal_json TEXT NOT NULL,
        selected_items_json TEXT NOT NULL,
        followups_json TEXT NOT NULL,
        scores_json TEXT NOT NULL,
        summary_text TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

def save_response(personal, selected_items, followups, scores, summary_text):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO responses 
        (submit_time, personal_json, selected_items_json, followups_json, scores_json, summary_text)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        json.dumps(personal, ensure_ascii=False),
        json.dumps(selected_items, ensure_ascii=False),
        json.dumps(followups, ensure_ascii=False),
        json.dumps(scores, ensure_ascii=False),
        summary_text
    ))
    conn.commit()
    conn.close()

def get_responses():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM responses ORDER BY id DESC", conn)
    conn.close()
    return df

def make_summary(scores, selected_items, followups):
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_score = sorted_scores[0][1] if sorted_scores else 0
    top_types = [name for name, score in sorted_scores if score == top_score]

    lines = ["微量元素疗法问卷计分总结", "", "一、各体质类型得分"]
    for name, score in sorted_scores:
        lines.append(f"- {name}：{score} 分")

    lines.append("")
    lines.append("二、结果概述")
    if top_score == 0:
        lines.append("本次问卷未勾选任何计分项目，因此暂无主要体质类型倾向。")
    else:
        lines.append(f"本次问卷中得分最高的类型为：{'、'.join(top_types)}，最高分为 {top_score} 分。")
        lines.append("该结果仅代表本问卷中所选项目按预设 X/XX 规则累计后的分数。")

    lines.append("")
    lines.append("三、已勾选项目")
    if selected_items:
        for item in selected_items:
            lines.append(f"- {item}")
            if item in followups and str(followups[item]).strip():
                lines.append(f"  补充：{str(followups[item]).strip()}")
    else:
        lines.append("无。")
    return "\n".join(lines)

def build_flat_dataframe(df, config):
    rows = []
    for _, r in df.iterrows():
        personal = json.loads(r["personal_json"])
        selected_items = json.loads(r["selected_items_json"])
        followups = json.loads(r["followups_json"])
        scores = json.loads(r["scores_json"])
        row = {"答卷ID": r["id"], "提交时间": r["submit_time"]}
        for field in config["personal_fields"]:
            label = field["label"]
            val = personal.get(label, "")
            row[label] = "；".join(val) if isinstance(val, list) else val
        row["已勾选项目"] = "；".join(selected_items)
        row["补充内容"] = "；".join([f"{k}：{v}" for k, v in followups.items() if str(v).strip()])
        for t in config["types"]:
            row[t] = scores.get(t, 0)
        row["总结"] = r["summary_text"]
        rows.append(row)
    return pd.DataFrame(rows)

def main():
    st.set_page_config(page_title="微量元素疗法 问卷", layout="wide")
    init_db()
    config = load_config()
    types = config["types"]

    st.title("微量元素疗法 问卷")

    page = st.sidebar.radio("页面", ["填写问卷", "查看数据与总结", "查看计分规则"])

    if page == "填写问卷":
        personal = {}
        selected_items = []
        followups = {}
        scores = {t: 0 for t in types}

        st.header("个人信息")
        for field in config["personal_fields"]:
            label = field["label"]
            ftype = field["type"]
            if ftype == "text":
                personal[label] = st.text_input(label)
            elif ftype == "textarea":
                personal[label] = st.text_area(label, placeholder=field.get("placeholder",""))
            elif ftype == "multiselect":
                personal[label] = st.multiselect(label, field.get("options", []))

        st.header("体质类型")
        for section in config["sections"]:
            st.subheader(section["title"])
            for idx, item in enumerate(section["items"]):
                key = f"{section['title']}_{idx}_{item['text']}"
                checked = st.checkbox(item["text"], key=key)
                if checked:
                    selected_items.append(item["text"])
                    for i, val in enumerate(item["scores"]):
                        scores[types[i]] += int(val)
                    if item.get("followup"):
                        followups[item["text"]] = st.text_input(item["followup"], key=f"followup_{key}")

        if st.button("提交问卷"):
            summary = make_summary(scores, selected_items, followups)
            save_response(personal, selected_items, followups, scores, summary)
            st.success("问卷已提交，结果已保存。")
            st.text_area("本次问卷总结", summary, height=300)

    elif page == "查看数据与总结":
        st.header("查看数据与总结")
        df = get_responses()
        if df.empty:
            st.info("目前还没有提交记录。")
            return

        flat_df = build_flat_dataframe(df, config)
        st.subheader("完整整理数据")
        st.dataframe(flat_df, use_container_width=True)

        csv = flat_df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("下载完整数据 CSV", csv, "微量元素疗法问卷完整数据.csv", "text/csv")

        st.subheader("单份问卷总结")
        selected_id = st.selectbox("选择答卷ID", flat_df["答卷ID"].tolist())
        selected_row = df[df["id"] == selected_id].iloc[0]
        st.text_area("总结", selected_row["summary_text"], height=350)
        st.download_button("下载该份总结 TXT", selected_row["summary_text"].encode("utf-8"), f"问卷总结_{selected_id}.txt", "text/plain")

        st.subheader("完整原始记录")
        st.dataframe(df, use_container_width=True)

    elif page == "查看计分规则":
        st.header("查看计分规则")
        rows = []
        for section in config["sections"]:
            for item in section["items"]:
                row = {"部分": section["title"], "项目": item["text"], "补充问题": item.get("followup","")}
                for i, t in enumerate(types):
                    row[t] = item["scores"][i]
                rows.append(row)
        rule_df = pd.DataFrame(rows)
        st.dataframe(rule_df, use_container_width=True)
        st.download_button("下载计分规则 CSV", rule_df.to_csv(index=False).encode("utf-8-sig"), "计分规则.csv", "text/csv")

if __name__ == "__main__":
    main()
