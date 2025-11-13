###############################################
# app.py : 나만의 맛집 지도 풀옵션 버전
# - SQLite 영구 저장
# - 도로명 주소 → 위도/경도 자동 변환
# - 지도 클릭으로 좌표 선택
# - 상세정보(주소/전화/링크/가격대/별점/태그/메모)
# - 즐겨찾기 표시
# - 검색/정렬/필터
# - CSV 백업/복원
###############################################

import sqlite3
from typing import List, Tuple, Optional, Dict, Any
from io import StringIO

import pandas as pd
import streamlit as st

import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable, GeocoderTimedOut

# =============== 전역 상수 ===============

DB_PATH: str = "restaurants.db"
DEFAULT_LAT: float = 37.566535   # 서울 시청 근처
DEFAULT_LON: float = 126.977969

PAGE_ADD_EDIT = "맛집 추가 / 수정"
PAGE_MAP = "지도에서 보기"
PAGE_LIST = "리스트 / 검색"
PAGE_DATA = "데이터 관리"


# =============== DB 유틸 함수 ===============

@st.cache_resource
def get_connection() -> sqlite3.Connection:
    """
    SQLite 연결을 반환하고,
    필요한 경우 테이블 및 컬럼을 자동 생성/확장한다.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """
    restaurants 테이블이 없으면 생성하고,
    기존 DB가 있을 경우 누락된 컬럼은 ALTER TABLE로 추가한다.
    """
    # 기본 테이블 생성 (없으면)
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
            favorite INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )

    # 누락 컬럼이 있을 수도 있으니 안전하게 보정
    cursor = conn.execute("PRAGMA table_info(restaurants)")
    existing_cols = {row[1] for row in cursor.fetchall()}

    # 추가 컬럼 목록 (이름, SQL)
    alter_statements = []
    if "favorite" not in existing_cols:
        alter_statements.append(
            "ALTER TABLE restaurants ADD COLUMN favorite INTEGER DEFAULT 0"
        )
    if "created_at" not in existing_cols:
        alter_statements.append(
            "ALTER TABLE restaurants ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        )
    if "updated_at" not in existing_cols:
        alter_statements.append(
            "ALTER TABLE restaurants ADD COLUMN updated_at TIMESTAMP"
        )

    for sql in alter_statements:
        conn.execute(sql)

    conn.commit()


def fetch_all_restaurants(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    전체 맛집 데이터를 DataFrame으로 가져온다.
    """
    df = pd.read_sql_query(
        "SELECT * FROM restaurants ORDER BY created_at DESC, id DESC",
        conn,
    )
    return df


def fetch_restaurant_by_id(
    conn: sqlite3.Connection, restaurant_id: int
) -> Optional[Dict[str, Any]]:
    """
    특정 id의 맛집 데이터를 dict로 반환.
    """
    cursor = conn.execute(
        "SELECT * FROM restaurants WHERE id = ?", (restaurant_id,)
    )
    row = cursor.fetchone()
    if row is None:
        return None

    columns = [desc[0] for desc in cursor.description]
    return {col: row[i] for i, col in enumerate(columns)}


def insert_restaurant(
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
    """
    새로운 맛집을 DB에 추가.
    """
    conn.execute(
        """
        INSERT INTO restaurants
        (name, category, memo, lat, lon, address, phone, url, price_range, rating, tags, favorite)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (name, category, memo, lat, lon, address, phone, url, price_range, rating, tags),
    )
    conn.commit()


def update_restaurant(
    conn: sqlite3.Connection,
    restaurant_id: int,
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
    """
    기존 맛집 정보를 수정.
    """
    conn.execute(
        """
        UPDATE restaurants
        SET name = ?, category = ?, memo = ?, lat = ?, lon = ?,
            address = ?, phone = ?, url = ?, price_range = ?,
            rating = ?, tags = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (name, category, memo, lat, lon, address, phone, url, price_range, rating, tags, restaurant_id),
    )
    conn.commit()


def delete_restaurant(conn: sqlite3.Connection, restaurant_id: int) -> None:
    """
    맛집 삭제.
    """
    conn.execute(
        "DELETE FROM restaurants WHERE id = ?",
        (restaurant_id,),
    )
    conn.commit()


def toggle_favorite(conn: sqlite3.Connection, restaurant_id: int, new_value: int) -> None:
    """
    즐겨찾기 ON/OFF (1 또는 0)
    """
    conn.execute(
        "UPDATE restaurants SET favorite = ? WHERE id = ?",
        (new_value, restaurant_id),
    )
    conn.commit()


# =============== 지오코딩 유틸 ===============

@st.cache_resource
def get_geocoder() -> Nominatim:
    """
    OpenStreetMap 기반 geopy Nominatim 객체 반환.
    """
    return Nominatim(user_agent="my-restaurant-map-app")


def geocode_address(address: str) -> Tuple[Optional[float], Optional[float]]:
    """
    도로명 주소(또는 일반 주소)를 입력받아 위도, 경도 반환.
    실패 시 (None, None) 반환.
    """
    if not address.strip():
        return None, None

    geolocator = get_geocoder()
    try:
        loc = geolocator.geocode(address)
        if loc:
            return loc.latitude, loc.longitude
        return None, None
    except (GeocoderUnavailable, GeocoderTimedOut):
        return None, None


# =============== 공통 유틸 ===============

def init_session_state() -> None:
    """
    Streamlit 세션 상태 초기화 (처음 실행 시 한 번).
    """
    if "current_lat" not in st.session_state:
        st.session_state["current_lat"] = DEFAULT_LAT
    if "current_lon" not in st.session_state:
        st.session_state["current_lon"] = DEFAULT_LON

    # 수정 모드에서 사용할 선택된 id
    if "edit_id" not in st.session_state:
        st.session_state["edit_id"] = None

    # 페이지 전환용
    if "page" not in st.session_state:
        st.session_state["page"] = PAGE_MAP


def safe_str(value: Any) -> str:
    """
    None을 빈 문자열로 안전하게 변환.
    """
    if value is None:
        return ""
    return str(value)


def build_price_options() -> List[str]:
    """
    가격대 선택 옵션 리스트.
    """
    return ["선택 안 함", "₩ (저렴)", "₩₩ (보통)", "₩₩₩ (조금 비쌈)", "₩₩₩₩ (매우 비쌈)"]


# =============== UI: 공통 스타일 ===============

def inject_css() -> None:
    """
    살짝 예쁜 느낌 나게 하는 CSS 주입.
    """
    css = """
    <style>
    /* 전체 배경 조금 더 부드럽게 */
    .main {
        background-color: #fafafa;
    }

    /* 카드 느낌 박스 */
    .restaurant-card {
        padding: 0.8rem 1.0rem;
        margin-bottom: 0.8rem;
        border-radius: 0.8rem;
        background-color: #ffffff;
        border: 1px solid #e5e5e5;
        box-shadow: 0 1px 3px rgba(15, 15, 15, 0.06);
    }

    .restaurant-card h4 {
        margin-bottom: 0.3rem;
    }

    .small-tag {
        display: inline-block;
        padding: 0.1rem 0.4rem;
        margin-right: 0.25rem;
        margin-bottom: 0.1rem;
        border-radius: 0.5rem;
        background-color: #f0f0f0;
        font-size: 0.75rem;
        color: #555;
    }

    .favorite-star {
        color: #ffb703;
        font-size: 1.2rem;
        margin-left: 0.3rem;
    }

    .subtle {
        color: #777;
        font-size: 0.8rem;
    }

    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


# =============== UI 페이지: 맛집 추가 / 수정 ===============

def page_add_or_edit(conn: sqlite3.Connection, df_all: pd.DataFrame) -> None:
    """
    맛집 추가 및 수정 페이지.
    """
    st.markdown("## 🍜 맛집 추가 / 수정")

    # ---- 상단: 편집할 맛집 선택 or 새로 만들기 ----
    edit_mode = False
    selected_row = None

    with st.expander("✏️ 이미 저장된 맛집을 수정하고 싶다면 여기서 선택", expanded=False):
        options = ["새 맛집 추가"] + [
            f"{row['id']} | {row['name']}" for _, row in df_all.iterrows()
        ]
        selected = st.selectbox("편집할 맛집 선택", options)

        if selected != "새 맛집 추가":
            edit_mode = True
            row_id = int(selected.split("|")[0].strip())
            st.session_state["edit_id"] = row_id
        else:
            st.session_state["edit_id"] = None

    if st.session_state["edit_id"] is not None:
        selected_row = fetch_restaurant_by_id(conn, st.session_state["edit_id"])
        if selected_row is None:
            st.warning("선택한 맛집을 찾을 수 없습니다. (삭제되었을 수도 있음)")
            st.session_state["edit_id"] = None
            edit_mode = False

    # ---- 중앙 레이아웃: 입력 폼 ----
    col_left, col_right = st.columns([2, 2])

    with col_left:
        st.markdown("### 1) 기본 정보")

        name = st.text_input(
            "맛집 이름 *",
            value=selected_row["name"] if selected_row else "",
        )

        category = st.text_input(
            "카테고리 (예: 한식, 카페, 라멘 등)",
            value=selected_row["category"] if selected_row and selected_row["category"] else "",
        )

        memo = st.text_area(
            "메모 (추천 메뉴, 분위기, 웨이팅 팁 등)",
            value=selected_row["memo"] if selected_row and selected_row["memo"] else "",
            height=120,
        )

        st.markdown("### 2) 위치 입력")

        # 주소 입력 → 좌표 찾기
        address_default = selected_row["address"] if selected_row and selected_row["address"] else ""
        address = st.text_input("도로명 주소 (선택)", value=address_default)

        if st.button("주소로 좌표 찾기", key="geocode_btn"):
            lat_found, lon_found = geocode_address(address)
            if lat_found is None:
                st.error("해당 주소로 위치를 찾을 수 없습니다. 주소를 다시 확인해 보세요.")
            else:
                st.success(f"주소로부터 좌표를 찾았습니다! (lat={lat_found:.6f}, lon={lon_found:.6f})")
                st.session_state["current_lat"] = float(lat_found)
                st.session_state["current_lon"] = float(lon_found)

        # 좌표 직접 입력
        lat_default = (
            float(selected_row["lat"]) if selected_row else float(st.session_state["current_lat"])
        )
        lon_default = (
            float(selected_row["lon"]) if selected_row else float(st.session_state["current_lon"])
        )

        lat = st.number_input(
            "위도 (lat)",
            format="%.6f",
            value=lat_default,
            key="lat_input_add",
        )
        lon = st.number_input(
            "경도 (lon)",
            format="%.6f",
            value=lon_default,
            key="lon_input_add",
        )

        # 입력값을 세션에도 동기화
        st.session_state["current_lat"] = float(lat)
        st.session_state["current_lon"] = float(lon)

    with col_right:
        st.markdown("### 3) 상세 정보")

        phone = st.text_input(
            "전화번호 (선택)",
            value=selected_row["phone"] if selected_row and selected_row["phone"] else "",
        )

        url = st.text_input(
            "링크 (네이버플레이스, 인스타 등)",
            value=selected_row["url"] if selected_row and selected_row["url"] else "",
        )

        price_options = build_price_options()
        default_price = "선택 안 함"
        if selected_row and selected_row["price_range"]:
            if selected_row["price_range"] in price_options:
                default_price = selected_row["price_range"]

        price_range = st.selectbox(
            "가격대 (선택)",
            options=price_options,
            index=price_options.index(default_price),
        )

        default_rating = 0.0
        if selected_row and selected_row["rating"] is not None:
            default_rating = float(selected_row["rating"])

        rating = st.slider(
            "별점 (선택)",
            min_value=0.0,
            max_value=5.0,
            step=0.5,
            value=default_rating,
        )

        tags = st.text_input(
            "태그 (쉼표로 구분, 예: 혼밥, 조용함, 디저트맛집)",
            value=selected_row["tags"] if selected_row and selected_row["tags"] else "",
        )

        st.markdown(
            "<span class='subtle'>지도를 클릭해서 좌표를 찍으면, 이 폼의 위도/경도도 자동으로 갱신됩니다 😊</span>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ---- 저장 / 삭제 버튼 ----
    btn_col1, btn_col2, btn_col3 = st.columns([1, 1, 3])

    with btn_col1:
        if st.button("✅ 저장", key="save_btn"):
            if not name.strip():
                st.error("맛집 이름은 반드시 입력해야 합니다.")
            else:
                price_value = "" if price_range == "선택 안 함" else price_range
                rating_value = None if rating == 0.0 else float(rating)

                if edit_mode and selected_row:
                    update_restaurant(
                        conn,
                        restaurant_id=selected_row["id"],
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
                    st.success(f"'{name}' 맛집 정보가 수정되었습니다.")
                else:
                    insert_restaurant(
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
                    st.success(f"'{name}' 맛집이 새로 추가되었습니다.")
                    # 새 추가 후 편집 모드 해제
                    st.session_state["edit_id"] = None

    with btn_col2:
        if edit_mode and selected_row:
            if st.button("🗑 삭제", key="delete_btn_confirm"):
                delete_restaurant(conn, selected_row["id"])
                st.session_state["edit_id"] = None
                st.success("맛집이 삭제되었습니다.")
                st.experimental_rerun()

    with btn_col3:
        if st.button("🧹 폼 초기화", key="reset_btn"):
            st.session_state["edit_id"] = None
            st.experimental_rerun()


# =============== UI 페이지: 지도에서 보기 ===============

def page_map(conn: sqlite3.Connection, df_all: pd.DataFrame) -> None:
    """
    전체 맛집을 지도에서 한눈에 보기 + 지도 클릭으로 좌표 선택.
    """
    st.markdown("## 🗺 지도에서 보기")

    # ---- 필터 영역 ----
    with st.expander("🔍 지도 필터 / 표시 옵션", expanded=True):
        cat_options = ["전체"] + sorted(
            [c for c in df_all["category"].dropna().unique().tolist() if c]
        )
        selected_cat = st.selectbox("카테고리 필터", cat_options, key="map_cat_filter")

        show_only_favorite = st.checkbox("⭐ 즐겨찾기만 보기", value=False)

        min_rating = st.slider(
            "최소 별점 필터 (0이면 필터 없음)",
            min_value=0.0,
            max_value=5.0,
            step=0.5,
            value=0.0,
        )

    filtered = df_all.copy()

    if selected_cat != "전체":
        filtered = filtered[filtered["category"] == selected_cat]

    if show_only_favorite:
        filtered = filtered[filtered["favorite"] == 1]

    if min_rating > 0:
        filtered = filtered[
            (filtered["rating"].notna()) & (filtered["rating"] >= min_rating)
        ]

    # ---- 지도 생성 ----
    center_lat = float(st.session_state["current_lat"])
    center_lon = float(st.session_state["current_lon"])

    m = folium.Map(location=[center_lat, center_lon], zoom_start=13)

    # 클러스터 사용 (마커 많아졌을 때 보기 좋게)
    marker_cluster = MarkerCluster().add_to(m)

    # 맛집 마커 표시
    if not filtered.empty:
        for _, row in filtered.iterrows():
            # 즐겨찾기 여부에 따라 아이콘/색 변경
            if row["favorite"] == 1:
                icon = folium.Icon(color="orange", icon="star")
            else:
                icon = folium.Icon(color="blue", icon="cutlery")

            popup_lines = [f"<b>{row['name']}</b>"]
            if isinstance(row["category"], str) and row["category"].strip():
                popup_lines.append(f"카테고리: {row['category']}")
            if row["rating"] is not None:
                popup_lines.append(f"⭐ {row['rating']:.1f} / 5.0")
            if isinstance(row["address"], str) and row["address"].strip():
                popup_lines.append(row["address"])

            popup_html = "<br>".join(popup_lines)

            folium.Marker(
                [row["lat"], row["lon"]],
                popup=popup_html,
                tooltip=row["name"],
                icon=icon,
            ).add_to(marker_cluster)

    # 현재 선택된 위치 마커
    folium.Marker(
        [center_lat, center_lon],
        popup="현재 선택된 위치",
        tooltip="현재 선택된 위치",
        icon=folium.Icon(color="red", icon="map-marker"),
    ).add_to(m)

    st.markdown("지도를 클릭하면, 클릭한 위치가 **현재 선택된 위치**로 업데이트됩니다.")
    map_data = st_folium(m, height=500, width="100%")

    if map_data and map_data.get("last_clicked") is not None:
        clicked = map_data["last_clicked"]
        clicked_lat = clicked["lat"]
        clicked_lon = clicked["lng"]
        st.session_state["current_lat"] = float(clicked_lat)
        st.session_state["current_lon"] = float(clicked_lon)
        st.info(f"선택된 위치 업데이트: lat={clicked_lat:.6f}, lon={clicked_lon:.6f}")


# =============== UI 페이지: 리스트 / 검색 ===============

def page_list(conn: sqlite3.Connection, df_all: pd.DataFrame) -> None:
    """
    리스트/검색 페이지: 카드 형태로 상세 표시, 즐겨찾기 토글, 수정 페이지로 이동 등.
    """
    st.markdown("## 📃 리스트 / 검색")

    if df_all.empty:
        st.info("아직 저장된 맛집이 없습니다. 먼저 맛집을 추가해 보세요!")
        return

    # ---- 필터 / 검색 / 정렬 ----
    with st.expander("🔍 필터 / 검색 / 정렬", expanded=True):
        cat_options = ["전체"] + sorted(
            [c for c in df_all["category"].dropna().unique().tolist() if c]
        )
        selected_cat = st.selectbox("카테고리 필터", cat_options, key="list_cat_filter")

        show_only_favorite = st.checkbox("⭐ 즐겨찾기만 보기", value=False, key="list_fav_only")

        keyword = st.text_input(
            "검색어 (이름, 태그, 메모, 주소에 대해 부분 검색)",
            value="",
        )

        sort_option = st.selectbox(
            "정렬 기준",
            ["최근 저장 순", "이름 순", "별점 높은 순"],
            index=0,
        )

    filtered = df_all.copy()

    if selected_cat != "전체":
        filtered = filtered[filtered["category"] == selected_cat]

    if show_only_favorite:
        filtered = filtered[filtered["favorite"] == 1]

    if keyword.strip():
        kw = keyword.strip()
        mask = (
            filtered["name"].astype(str).str.contains(kw, case=False) |
            filtered["tags"].astype(str).str.contains(kw, case=False) |
            filtered["memo"].astype(str).str.contains(kw, case=False) |
            filtered["address"].astype(str).str.contains(kw, case=False)
        )
        filtered = filtered[mask]

    if sort_option == "최근 저장 순":
        filtered = filtered.sort_values(["created_at", "id"], ascending=[False, False])
    elif sort_option == "이름 순":
        filtered = filtered.sort_values(["name", "id"], ascending=[True, True])
    elif sort_option == "별점 높은 순":
        filtered = filtered.sort_values(["rating", "created_at"], ascending=[False, False])

    st.markdown(f"총 **{len(filtered)}개**의 맛집이 조건에 맞습니다.")

    # ---- 카드 렌더링 ----
    for _, row in filtered.iterrows():
        with st.container():
            st.markdown("<div class='restaurant-card'>", unsafe_allow_html=True)

            title = f"{row['name']}"
            if isinstance(row["category"], str) and row["category"].strip():
                title += f" ({row['category']})"

            fav = "⭐" if row["favorite"] == 1 else "☆"
            st.markdown(
                f"<h4>{title} <span class='favorite-star'>{fav}</span></h4>",
                unsafe_allow_html=True,
            )

            # 한 줄 정보들
            if isinstance(row["address"], str) and row["address"].strip():
                st.markdown(f"- 📍 **주소**: {row['address']}")
            st.markdown(f"- 🗺 **좌표**: {row['lat']:.6f}, {row['lon']:.6f}")

            info_line = []
            if isinstance(row["phone"], str) and row["phone"].strip():
                info_line.append(f"☎ {row['phone']}")
            if isinstance(row["price_range"], str) and row["price_range"].strip():
                info_line.append(f"💰 {row['price_range']}")
            if row["rating"] is not None:
                info_line.append(f"⭐ {row['rating']:.1f}/5.0")

            if info_line:
                st.markdown("- " + " · ".join(info_line))

            if isinstance(row["tags"], str) and row["tags"].strip():
                tag_html = "".join(
                    f"<span class='small-tag'>{t.strip()}</span>"
                    for t in row["tags"].split(",")
                    if t.strip()
                )
                st.markdown(tag_html, unsafe_allow_html=True)

            if isinstance(row["memo"], str) and row["memo"].strip():
                st.markdown(f"**메모**: {row['memo']}")

            if isinstance(row["url"], str) and row["url"].strip():
                st.markdown(f"[🔗 링크 바로가기]({row['url']})")

            st.markdown(
                f"<span class='subtle'>저장 시각: {safe_str(row['created_at'])}</span>",
                unsafe_allow_html=True,
            )

            # 버튼들
            c1, c2, c3, c4 = st.columns([1, 1, 1, 4])
            with c1:
                fav_label = "즐겨찾기 해제" if row["favorite"] == 1 else "즐겨찾기에 추가"
                if st.button(fav_label, key=f"fav_{row['id']}"):
                    new_val = 0 if row["favorite"] == 1 else 1
                    toggle_favorite(conn, row["id"], new_val)
                    st.experimental_rerun()

            with c2:
                if st.button("수정", key=f"edit_{row['id']}"):
                    st.session_state["edit_id"] = row["id"]
                    st.session_state["page"] = PAGE_ADD_EDIT
                    st.experimental_rerun()

            with c3:
                if st.button("삭제", key=f"del_{row['id']}"):
                    delete_restaurant(conn, row["id"])
                    st.experimental_rerun()

            st.markdown("</div>", unsafe_allow_html=True)


# =============== UI 페이지: 데이터 관리 (백업/복원) ===============

def page_data(conn: sqlite3.Connection, df_all: pd.DataFrame) -> None:
    """
    CSV 백업 / 복원 / Raw 데이터 보기 페이지.
    """
    st.markdown("## 💾 데이터 관리 (백업 / 복원)")

    st.markdown("### 1) CSV로 백업 다운로드")
    if df_all.empty:
        st.info("현재 저장된 데이터가 없습니다. 먼저 몇 개의 맛집을 추가해보세요.")
    else:
        csv_buffer = StringIO()
        df_all.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 CSV로 다운로드",
            data=csv_buffer.getvalue(),
            file_name="restaurants_backup.csv",
            mime="text/csv",
        )

    st.markdown("---")
    st.markdown("### 2) CSV에서 복원 / 추가")

    uploaded = st.file_uploader(
        "복원할 CSV 파일을 업로드하세요 (컬럼 이름이 맞아야 합니다)",
        type=["csv"],
        key="upload_csv",
    )

    if uploaded is not None:
        try:
            df_new = pd.read_csv(uploaded)
            st.write("업로드한 CSV 미리보기:")
            st.dataframe(df_new.head())

            if st.button("이 CSV를 기반으로 기존 + 신규 데이터 병합 저장", key="merge_csv_btn"):
                # 간단하게: CSV에 있는 것들을 모두 추가 삽입 (중복 체크는 생략)
                required_cols = {"name", "lat", "lon"}
                if not required_cols.issubset(set(df_new.columns)):
                    st.error("CSV에 name, lat, lon 컬럼이 반드시 포함되어야 합니다.")
                else:
                    inserted_count = 0
                    for _, row in df_new.iterrows():
                        insert_restaurant(
                            conn,
                            name=safe_str(row.get("name", "")).strip(),
                            category=safe_str(row.get("category", "")).strip(),
                            memo=safe_str(row.get("memo", "")).strip(),
                            lat=float(row.get("lat", DEFAULT_LAT)),
                            lon=float(row.get("lon", DEFAULT_LON)),
                            address=safe_str(row.get("address", "")).strip(),
                            phone=safe_str(row.get("phone", "")).strip(),
                            url=safe_str(row.get("url", "")).strip(),
                            price_range=safe_str(row.get("price_range", "")).strip(),
                            rating=float(row["rating"]) if pd.notna(row.get("rating", None)) else None,
                            tags=safe_str(row.get("tags", "")).strip(),
                        )
                        inserted_count += 1
                    st.success(f"CSV로부터 {inserted_count}개의 맛집이 추가/병합 되었습니다.")
                    st.experimental_rerun()

        except Exception as e:
            st.error(f"CSV를 읽는 중 오류 발생: {e}")

    st.markdown("---")
    st.markdown("### 3) Raw 데이터 테이블 보기")

    if df_all.empty:
        st.info("현재 저장된 데이터가 없습니다.")
    else:
        st.dataframe(df_all)


# =============== 메인 진입점 ===============

def main() -> None:
    st.set_page_config(
        page_title="나만의 맛집 지도",
        layout="wide",
    )

    inject_css()
    init_session_state()

    conn = get_connection()
    df_all = fetch_all_restaurants(conn)

    # ---- 사이드바: 내비게이션 ----
    with st.sidebar:
        st.markdown("## 🍽 나만의 맛집 지도")
        st.markdown("**원하는 기능을 선택하세요**")

        page = st.radio(
            "페이지 이동",
            options=[PAGE_MAP, PAGE_ADD_EDIT, PAGE_LIST, PAGE_DATA],
            index=[PAGE_MAP, PAGE_ADD_EDIT, PAGE_LIST, PAGE_DATA].index(
                st.session_state["page"]
            ),
            key="page",
        )

        st.markdown("---")
        st.markdown("### 📊 간단 통계")
        st.write(f"- 총 맛집 수: **{len(df_all)}** 개")
        fav_count = int((df_all["favorite"] == 1).sum()) if not df_all.empty else 0
        st.write(f"- 즐겨찾기 수: ⭐ **{fav_count}** 개")

        if not df_all.empty:
            avg_rating = df_all["rating"].dropna().mean()
            if pd.notna(avg_rating):
                st.write(f"- 평균 별점: **{avg_rating:.2f} / 5.0**")

    # ---- 메인 페이지 라우팅 ----
    if page == PAGE_ADD_EDIT:
        page_add_or_edit(conn, df_all)
    elif page == PAGE_MAP:
        page_map(conn, df_all)
    elif page == PAGE_LIST:
        page_list(conn, df_all)
    elif page == PAGE_DATA:
        page_data(conn, df_all)
    else:
        # 혹시 모를 예외
        st.write("알 수 없는 페이지입니다.")


if __name__ == "__main__":
    main()
