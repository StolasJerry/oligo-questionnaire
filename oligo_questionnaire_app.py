
import streamlit as st
import pandas as pd
import sqlite3
import json
from datetime import datetime, date
from pathlib import Path
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

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
        section_scores_json TEXT NOT NULL DEFAULT '{}',
        summary_text TEXT NOT NULL
    )
    """)
    # Existing old database compatibility: add section_scores_json if missing.
    c.execute("PRAGMA table_info(responses)")
    columns = [row[1] for row in c.fetchall()]
    if "section_scores_json" not in columns:
        c.execute("ALTER TABLE responses ADD COLUMN section_scores_json TEXT NOT NULL DEFAULT '{}'")
    conn.commit()
    conn.close()


def save_response(personal, selected_items, followups, scores, section_scores, summary_text):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO responses
        (submit_time, personal_json, selected_items_json, followups_json, scores_json, section_scores_json, summary_text)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        json.dumps(personal, ensure_ascii=False),
        json.dumps(selected_items, ensure_ascii=False),
        json.dumps(followups, ensure_ascii=False),
        json.dumps(scores, ensure_ascii=False),
        json.dumps(section_scores, ensure_ascii=False),
        summary_text
    ))
    conn.commit()
    row_id = c.lastrowid
    conn.close()
    return row_id


def get_responses():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM responses ORDER BY id DESC", conn)
    conn.close()
    return df


def parse_date_to_display(value):
    if value is None or value == "":
        return ""
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    return str(value)


def date_widget(label, key):
    st.caption("格式：DD/MM/YYYY")
    mode = st.radio(
        label,
        ["选择日期", "手动输入"],
        horizontal=True,
        key=f"{key}_mode",
        label_visibility="collapsed"
    )
    if mode == "选择日期":
        val = st.date_input(label, value=None, format="DD/MM/YYYY", key=key)
        return parse_date_to_display(val)
    return st.text_input(label, placeholder="DD/MM/YYYY", key=key)


def height_widget(label, key):
    col1, col2 = st.columns([2, 1])
    with col1:
        value = st.number_input(label, min_value=0.0, step=0.1, key=f"{key}_value")
    with col2:
        unit = st.selectbox("单位", ["cm", "m", "inch", "ft"], key=f"{key}_unit")
    if value <= 0:
        return {"原始输入": "", "单位": unit, "SI": ""}
    if unit == "cm":
        si_m = value / 100
    elif unit == "m":
        si_m = value
    elif unit == "inch":
        si_m = value * 0.0254
    else:
        si_m = value * 0.3048
    st.caption(f"自动换算：{si_m:.3f} m")
    return {"原始输入": value, "单位": unit, "SI": f"{si_m:.3f} m"}


def weight_widget(label, key):
    col1, col2 = st.columns([2, 1])
    with col1:
        value = st.number_input(label, min_value=0.0, step=0.1, key=f"{key}_value")
    with col2:
        unit = st.selectbox("单位", ["kg", "lb", "斤"], key=f"{key}_unit")
    if value <= 0:
        return {"原始输入": "", "单位": unit, "SI": ""}
    if unit == "kg":
        si_kg = value
    elif unit == "lb":
        si_kg = value * 0.45359237
    else:
        si_kg = value * 0.5
    st.caption(f"自动换算：{si_kg:.2f} kg")
    return {"原始输入": value, "单位": unit, "SI": f"{si_kg:.2f} kg"}


def format_value(value):
    if isinstance(value, list):
        return "；".join(value)
    if isinstance(value, dict):
        parts = []
        for k, v in value.items():
            if isinstance(v, dict):
                inner = "，".join([f"{ik}: {iv}" for ik, iv in v.items() if str(iv).strip()])
                if inner:
                    parts.append(f"{k}: {inner}")
            elif isinstance(v, list):
                if v:
                    parts.append(f"{k}: {'、'.join(v)}")
            else:
                if str(v).strip():
                    parts.append(f"{k}: {v}")
        return "；".join(parts)
    return str(value)


def followup_widget(item, key):
    ftype = item.get("followup_type", "text")
    label = item.get("followup", "补充说明")

    if ftype == "stool_inline":
        st.markdown("大便情况：")
        cols = st.columns(4)
        with cols[0]:
            freq = st.text_input("频率", key=f"{key}_stool_freq", placeholder="填写")
        with cols[1]:
            color = st.text_input("颜色", key=f"{key}_stool_color", placeholder="填写")
        with cols[2]:
            texture = st.text_input("黏稠度", key=f"{key}_stool_texture", placeholder="填写")
        with cols[3]:
            smell = st.text_input("气味", key=f"{key}_stool_smell", placeholder="填写")
        return {"频率": freq, "颜色": color, "黏稠度": texture, "气味": smell}

    if ftype == "menopause":
        st.markdown("补充：更年期")
        disorder = st.checkbox("更年期紊乱", key=f"{key}_menopause_disorder")
        result = {"更年期紊乱": "是" if disorder else "否"}
        if disorder:
            result["发病日期"] = date_widget("发病日期", key=f"{key}_menopause_date")
        return result

    if ftype == "hormone":
        start = date_widget("开始时期", key=f"{key}_hormone_start")
        return {"开始时期": start}

    return st.text_input(label, key=f"followup_{key}")


def make_summary(scores, selected_items, followups, section_scores):
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_score = sorted_scores[0][1] if sorted_scores else 0
    top_types = [name for name, score in sorted_scores if score == top_score]

    lines = []
    lines.append("微量元素疗法问卷计分总结")
    lines.append("")
    lines.append("一、各体质类型得分")
    for name, score in sorted_scores:
        lines.append(f"- {name}：{score} 分")

    lines.append("")
    lines.append("二、结果概述")
    if top_score == 0:
        lines.append("本次问卷未勾选任何计分项目，因此暂无主要体质类型倾向。")
    else:
        lines.append(f"本次问卷中得分最高的类型为：{'、'.join(top_types)}，最高分为 {top_score} 分。")

    lines.append("")
    lines.append("三、分项总结")
    if section_scores:
        for section, sc in sorted(section_scores.items(), key=lambda x: sum(x[1].values()), reverse=True):
            total = sum(sc.values())
            if total == 0:
                continue
            type_sorted = sorted(sc.items(), key=lambda x: x[1], reverse=True)
            top_in_section_score = type_sorted[0][1]
            top_in_section = [name for name, score in type_sorted if score == top_in_section_score and score > 0]
            iii_score = next((v for k, v in sc.items() if "III" in k), 0)
            iv_score = next((v for k, v in sc.items() if "IV" in k), 0)
            lines.append(f"- {section}：总分 {total} 分；最高项：{'、'.join(top_in_section) if top_in_section else '无'}（{top_in_section_score} 分）；III 项 {iii_score} 分，IV 项 {iv_score} 分。")
            details = "；".join([f"{name} {score} 分" for name, score in type_sorted])
            lines.append(f"  分布：{details}")
    else:
        lines.append("暂无分项得分。")

    lines.append("")
    lines.append("四、已勾选项目")
    if selected_items:
        for item in selected_items:
            lines.append(f"- {item}")
            if item in followups and format_value(followups[item]).strip():
                lines.append(f"  补充：{format_value(followups[item])}")
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
        section_scores = json.loads(r.get("section_scores_json", "{}") or "{}")

        row = {"答卷ID": r["id"], "提交时间": r["submit_time"]}
        for field in config["personal_fields"]:
            label = field["label"]
            row[label] = format_value(personal.get(label, ""))

        row["已勾选项目"] = "；".join(selected_items)
        row["补充内容"] = "；".join([f"{k}：{format_value(v)}" for k, v in followups.items() if format_value(v).strip()])
        for t in config["types"]:
            row[t] = scores.get(t, 0)
        for section, sc in section_scores.items():
            row[f"{section}_总分"] = sum(sc.values())
            for t in config["types"]:
                row[f"{section}_{t}"] = sc.get(t, 0)
        row["总结"] = r["summary_text"]
        rows.append(row)
    return pd.DataFrame(rows)


def split_text_by_width(c, text, max_width, font_name, font_size):
    text = str(text)
    lines, current = [], ""
    for ch in text:
        test = current + ch
        if c.stringWidth(test, font_name, font_size) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def create_pdf_bytes(personal, selected_items, followups, scores, section_scores, summary_text):
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "STSong-Light"

    width, height = A4
    x = 18 * mm
    y = height - 18 * mm
    max_width = width - 36 * mm

    def draw_line(text, size=10, leading=6*mm):
        nonlocal y
        c.setFont(font, size)
        for line in split_text_by_width(c, text, max_width, font, size):
            if y < 18 * mm:
                c.showPage()
                c.setFont(font, size)
                y = height - 18 * mm
            c.drawString(x, y, line)
            y -= leading

    draw_line("微量元素疗法 问卷记录", size=16, leading=9*mm)
    draw_line(f"生成时间：{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", size=9)
    draw_line("")

    draw_line("一、填表人信息", size=13, leading=8*mm)
    for key in ["姓名", "填表日期"]:
        if personal.get(key):
            draw_line(f"{key}：{format_value(personal.get(key))}", size=10)

    draw_line("")
    draw_line("二、总结", size=13, leading=8*mm)
    for line in summary_text.splitlines():
        draw_line(line, size=10)

    draw_line("")
    draw_line("三、完整已勾选选项", size=13, leading=8*mm)
    if selected_items:
        for item in selected_items:
            draw_line(f"- {item}", size=10)
            if item in followups and format_value(followups[item]).strip():
                draw_line(f"  补充：{format_value(followups[item])}", size=10)
    else:
        draw_line("无。", size=10)

    c.save()
    buffer.seek(0)
    return buffer.read()


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
        section_scores = {}

        st.header("个人信息")
        for idx, field in enumerate(config["personal_fields"]):
            label = field["label"]
            ftype = field["type"]
            key = f"personal_{idx}_{label}"

            if ftype == "text":
                personal[label] = st.text_input(label, key=key)
            elif ftype == "textarea":
                personal[label] = st.text_area(label, placeholder=field.get("placeholder", ""), key=key)
            elif ftype == "multiselect":
                personal[label] = st.multiselect(label, field.get("options", []), key=key)
            elif ftype == "date":
                personal[label] = date_widget(label, key=key)
            elif ftype == "height":
                personal[label] = height_widget(label, key=key)
            elif ftype == "weight":
                personal[label] = weight_widget(label, key=key)

        st.header("体质类型")
        for section in config["sections"]:
            section_name = section["title"]
            section_scores[section_name] = {t: 0 for t in types}
            st.subheader(section_name)
            for idx, item in enumerate(section["items"]):
                key = f"{section_name}_{idx}_{item['text']}"
                checked = st.checkbox(item["text"], key=key)
                if checked:
                    selected_items.append(item["text"])
                    for i, val in enumerate(item["scores"]):
                        val = int(val)
                        scores[types[i]] += val
                        section_scores[section_name][types[i]] += val
                    if item.get("followup"):
                        followups[item["text"]] = followup_widget(item, key)

        if st.button("提交问卷"):
            summary = make_summary(scores, selected_items, followups, section_scores)
            row_id = save_response(personal, selected_items, followups, scores, section_scores, summary)
            st.success("问卷已提交，结果已保存。")
            st.text_area("本次问卷总结", summary, height=430)

            pdf_bytes = create_pdf_bytes(personal, selected_items, followups, scores, section_scores, summary)
            person_name = personal.get("姓名", "") or f"答卷_{row_id}"
            st.download_button(
                "下载本次问卷 PDF",
                data=pdf_bytes,
                file_name=f"微量元素疗法问卷_{person_name}_{row_id}.pdf",
                mime="application/pdf"
            )

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

        st.subheader("单份问卷总结与 PDF")
        selected_id = st.selectbox("选择答卷ID", flat_df["答卷ID"].tolist())
        selected_row = df[df["id"] == selected_id].iloc[0]

        personal = json.loads(selected_row["personal_json"])
        selected_items = json.loads(selected_row["selected_items_json"])
        followups = json.loads(selected_row["followups_json"])
        scores = json.loads(selected_row["scores_json"])
        section_scores = json.loads(selected_row.get("section_scores_json", "{}") or "{}")
        summary_text = selected_row["summary_text"]

        st.text_area("总结", summary_text, height=430)
        st.download_button("下载该份总结 TXT", summary_text.encode("utf-8"), f"问卷总结_{selected_id}.txt", "text/plain")

        pdf_bytes = create_pdf_bytes(personal, selected_items, followups, scores, section_scores, summary_text)
        person_name = personal.get("姓名", "") or f"答卷_{selected_id}"
        st.download_button("下载该份完整 PDF", data=pdf_bytes, file_name=f"微量元素疗法问卷_{person_name}_{selected_id}.pdf", mime="application/pdf")

        st.subheader("完整原始记录")
        st.dataframe(df, use_container_width=True)

    elif page == "查看计分规则":
        st.header("查看计分规则")
        rows = []
        for section in config["sections"]:
            for item in section["items"]:
                row = {"部分": section["title"], "项目": item["text"], "补充问题": item.get("followup", ""), "补充类型": item.get("followup_type", "")}
                for i, t in enumerate(types):
                    row[t] = item["scores"][i]
                rows.append(row)
        rule_df = pd.DataFrame(rows)
        st.dataframe(rule_df, use_container_width=True)
        st.download_button("下载计分规则 CSV", rule_df.to_csv(index=False).encode("utf-8-sig"), "计分规则.csv", "text/csv")

if __name__ == "__main__":
    main()
