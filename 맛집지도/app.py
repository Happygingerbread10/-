import sqlite3
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st

import folium
from streamlit_folium import st_folium


DB_PATH = "restaurants.db"
DEFAULT_LAT = 37.566535   # 서울 시청 근처
DEFAULT_LON = 126.977969


# -------------------------
# DB 관련 함수
# -------------------------
@st.cache_resource
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS restaurants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category TEXT,
            memo TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            address TEXT,
            phone TEXT,
            url TEXT,
            price_range TEXT,
            rating REAL,
            tags TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def load_restaurants(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT * FROM restaurants ORDER BY created_at DESC, id DESC",
        conn
    )
    return df


def add_restaurant(
    conn: sqlite3.Connection,
    name: str,
    category: str,
    memo: str,
    lat: float,
    lon: float,
    address: str,
    phone: str,
    url: str,
    price_range: str,
    rating: Optional[float],
    tags: str,
) -> None:
    conn.execute(
        """
        INSERT INTO restaurants
        (name, category, memo, lat, lon, address, phone, url, price_range, rating, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, category, memo, lat, lon, address, phone, url, price_range, rating, tags),
    )
    conn.commit()


def delete_restaurant(conn: sqlite3.Connection, row_id: int) -> None:
    conn.execute("DELETE FROM restaurants WHERE id = ?", (row_id,))
    conn.commit()


# -------------------------
# 세션 상태 초기화
# -------------------------
def init_session_state() -> None:
    if "current_lat" not in st.session_state:
        st.session_state["current_lat"] = DEFAULT_LAT
    if "current_lon" not in st.session_state:
        st.session_state["current_lon"] = DEFAULT_LON


# -------------------------
# 메인 앱
# -------------------------
def main() -> None:
    st.set_page_config(page_title="나만의 맛집 지도", layout="wide")
    init_session_state()

    st.title("🍽 나만의 맛집 지도")
    st.caption("왼쪽에서 맛집 정보를 입력하고, 오른쪽 지도에서 위치를 콕 찍어 저장해 보세요!")

    conn = get_connection()
    df = load_restaurants(conn)

    # 레이아웃: 왼쪽(폼) / 오른쪽(지도)
    col_left, col_right = st.columns([2, 3])

    # -------------------------
    # 왼쪽: 맛집 입력 폼
    # -------------------------
    with col_left:
        st.subheader("➕ 맛집 추가")

        with st.form("add_form", clear_on_submit=True):
            name = st.text_input("🍜 맛집 이름 *")
            category = st.text_input("📂 카테고리 (예: 한식, 카페, 라멘 등)", value="")
            memo = st.text_area("📝 메모 (추천 메뉴, 분위기 등)", height=80)

            address = st.text_input("📍 주소 (선택)", value="")
            phone = st.text_input("☎ 전화번호 (선택)", value="")
            url = st.text_input("🔗 링크 (네이버플레이스, 인스타 등)", value="")

            price_range = st.selectbox(
                "💰 가격대 (선택)",
                ["선택 안 함", "₩ (저렴)", "₩₩ (보통)", "₩₩₩ (조금 비쌈)", "₩₩₩₩ (매우 비쌈)"],
                index=0,
            )
            rating = st.slider(
                "⭐ 별점 (선택)",
                min_value=0.0, max_value=5.0, step=0.5, value=0.0
            )
            tags = st.text_input(
                "🏷 태그 (쉼표로 구분, 예: 혼밥, 조용함, 디저트맛집)",
                value=""
            )

            st.markdown("---")
            st.markdown("**지도에서 선택된 위치(위도/경도)**")
            lat_col, lon_col = st.columns(2)
            with lat_col:
                st.number_input(
                    "위도 (lat)",
                    value=float(st.session_state["current_lat"]),
                    format="%.6f",
                    disabled=True,
                )
            with lon_col:
                st.number_input(
                    "경도 (lon)",
                    value=float(st.session_state["current_lon"]),
                    format="%.6f",
                    disabled=True,
                )
            st.caption("👉 오른쪽 지도를 클릭하면 이 좌표가 자동으로 변경됩니다.")

            submitted = st.form_submit_button("✅ 맛집 저장하기")

            if submitted:
                if not name.strip():
                    st.error("맛집 이름은 반드시 입력해야 합니다!")
                else:
                    price_value = "" if price_range == "선택 안 함" else price_range
                    rating_value = None if rating == 0.0 else float(rating)

                    add_restaurant(
                        conn,
                        name=name.strip(),
                        category=category.strip(),
                        memo=memo.strip(),
                        lat=float(st.session_state["current_lat"]),
                        lon=float(st.session_state["current_lon"]),
                        address=address.strip(),
                        phone=phone.strip(),
                        url=url.strip(),
                        price_range=price_value,
                        rating=rating_value,
                        tags=tags.strip(),
                    )
                    st.success(f"'{name}' 맛집이 저장되었습니다 ✅")

        st.markdown("---")
        st.subheader("📃 저장된 맛집 리스트")

        if df.empty:
            st.info("아직 저장된 맛집이 없습니다.")
        else:
            for _, row in df.iterrows():
                with st.container():
                    st.markdown(f"**{row['name']}** ({row['category'] if row['category'] else '카테고리 없음'})")
                    st.markdown(f"- 📍 주소: {row['address'] if row['address'] else '정보 없음'}")
                    st.markdown(f"- 🗺 좌표: {row['lat']:.6f}, {row['lon']:.6f}")
                    if row["rating"] is not None:
                        st.markdown(f"- ⭐ 별점: {row['rating']:.1f} / 5.0")
                    if row["tags"]:
                        st.markdown(f"- 🏷 태그: {row['tags']}")
                    if row["memo"]:
                        st.markdown(f"- 📝 메모: {row['memo']}")
                    if row["url"]:
                        st.markdown(f"- 🔗 [링크 바로가기]({row['url']})")
                    col_del, _ = st.columns([1, 4])
                    with col_del:
                        if st.button("🗑 삭제", key=f"del_{row['id']}"):
                            delete_restaurant(conn, int(row["id"]))
                            st.experimental_rerun()
                    st.markdown("---")

    # -------------------------
    # 오른쪽: 지도 (클릭해서 위치 선택)
    # -------------------------
    with col_right:
        st.subheader("🗺 지도에서 위치 선택하기")

        # 현재 선택된 위치 기준으로 지도 센터 잡기
        center_lat = float(st.session_state["current_lat"])
        center_lon = float(st.session_state["current_lon"])

        m = folium.Map(location=[center_lat, center_lon], zoom_start=13)

        # 이미 저장된 맛집들 마커 표시
        if not df.empty:
            for _, row in df.iterrows():
                popup_text = f"{row['name']}"
                if row["category"]:
                    popup_text += f" ({row['category']})"
                if row["rating"] is not None:
                    popup_text += f" ⭐{row['rating']:.1f}"
                folium.Marker(
                    [row["lat"], row["lon"]],
                    popup=popup_text,
                    tooltip=popup_text,
                ).add_to(m)

        # 현재 선택된 위치 마커
        folium.Marker(
            [center_lat, center_lon],
            popup="현재 선택된 위치",
            tooltip="현재 선택된 위치",
            icon=folium.Icon(color="red", icon="map-marker"),
        ).add_to(m)

        st.markdown("지도를 클릭하면, 그 위치가 **현재 선택된 위치**가 되고 왼쪽 폼에 반영됩니다.")

        map_data: Dict[str, Any] = st_folium(m, height=500, width="100%")

        # 지도 클릭 시 좌표 업데이트
        if map_data and map_data.get("last_clicked") is not None:
            clicked = map_data["last_clicked"]
            clicked_lat = clicked["lat"]
            clicked_lon = clicked["lng"]
            st.session_state["current_lat"] = float(clicked_lat)
            st.session_state["current_lon"] = float(clicked_lon)
            st.info(f"선택된 위치: lat={clicked_lat:.6f}, lon={clicked_lon:.6f}")


if __name__ == "__main__":
    main()
