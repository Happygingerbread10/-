import streamlit as st
import sqlite3
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable, GeocoderTimedOut
import folium
from streamlit_folium import st_folium

DB_PATH = "restaurants.db"

# ------------------------
# DB 연결 + 테이블 생성
# ------------------------
@st.cache_resource
def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
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
    return conn

def load_restaurants(conn):
    df = pd.read_sql_query("SELECT * FROM restaurants ORDER BY created_at DESC", conn)
    return df

def add_restaurant(conn, name, category, memo, lat, lon,
                   address, phone, url, price_range, rating, tags):
    conn.execute(
        """
        INSERT INTO restaurants
        (name, category, memo, lat, lon, address, phone, url, price_range, rating, tags)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, category, memo, lat, lon, address, phone, url, price_range, rating, tags),
    )
    conn.commit()

def delete_restaurant(conn, row_id):
    conn.execute("DELETE FROM restaurants WHERE id = ?", (row_id,))
    conn.commit()

# ------------------------
# 지오코딩: 도로명 주소 → 위도/경도
# ------------------------
@st.cache_resource
def get_geocoder():
    return Nominatim(user_agent="my-restaurant-map-app")

def geocode_address(address: str):
    geolocator = get_geocoder()
    try:
        loc = geolocator.geocode(address)
        if loc:
            return loc.latitude, loc.longitude
        return None, None
    except (GeocoderUnavailable, GeocoderTimedOut):
        return None, None

# ------------------------
# 기본 UI 설정
# ------------------------
st.set_page_config(
    page_title="나만의 맛집 지도",
    layout="wide",
)

# 상단 헤더 영역
left_header, right_header = st.columns([3, 1])
with left_header:
    st.markdown("## 🍽️ 나만의 맛집 지도")
    st.markdown("**내가 직접 모은 맛집을 위치 + 상세정보와 함께 저장하고, 지도에서 한눈에 보기!**")
with right_header:
    # 원하면 여기다 로고 이미지 URL 넣어도 됨
    st.markdown(" ")
    st.markdown(" ")
    st.markdown("✨ *by Me*")

conn = get_connection()

# ------------------------
# 위치 기본값 (서울 시청 근처)
# ------------------------
if "lat" not in st.session_state:
    st.session_state["lat"] = 37.566535
if "lon" not in st.session_state:
    st.session_state["lon"] = 126.977969

# ------------------------
# 레이아웃: 왼쪽(입력/리스트) - 오른쪽(지도)
# ------------------------
left_col, right_col = st.columns([2, 3])

# ==========================================
# 왼쪽: 맛집 추가 + 리스트
# ==========================================
with left_col:
    st.markdown("### ➕ 맛집 추가하기")

    # 입력 폼 (form 안 써도 되지만, 그룹 느낌만)
    with st.container():
        st.markdown("#### 1) 기본 정보")
        name = st.text_input("🍜 맛집 이름 *")
        category = st.text_input("📂 카테고리 (예: 한식, 카페, 라멘 등)", value="")
        memo = st.text_area("📝 메모 (추천 메뉴, 분위기 등)", height=80)

        st.markdown("#### 2) 위치 선택 (세 가지 방법 중 택1 또는 조합 사용 가능)")

        # (1) 도로명 주소로 검색
        st.markdown("**① 도로명 주소로 검색해서 좌표 찾기**")
        address = st.text_input("📍 도로명 주소 (예: 서울특별시 중구 세종대로 110)")
        addr_btn = st.button("주소로 좌표 찾기")

        if addr_btn and address.strip():
            lat_found, lon_found = geocode_address(address.strip())
            if lat_found is None:
                st.error("해당 주소로 위치를 찾을 수 없습니다. 주소를 다시 확인해 보세요.")
            else:
                st.session_state["lat"] = lat_found
                st.session_state["lon"] = lon_found
                st.success(f"주소로부터 좌표를 찾았습니다! (lat={lat_found:.6f}, lon={lon_found:.6f})")

        # (2) 좌표 직접 입력
        st.markdown("**② 좌표 직접 입력하기**")
        col_lat, col_lon = st.columns(2)
        with col_lat:
            lat = st.number_input(
                "위도 (lat)",
                format="%.6f",
                value=float(st.session_state["lat"]),
                key="lat_input"
            )
        with col_lon:
            lon = st.number_input(
                "경도 (lon)",
                format="%.6f",
                value=float(st.session_state["lon"]),
                key="lon_input"
            )

        # number_input 값이 바뀌면 세션에도 반영
        st.session_state["lat"] = float(lat)
        st.session_state["lon"] = float(lon)

        st.markdown("**③ 오른쪽 지도에서 직접 클릭해서 선택하기**  
(지도를 클릭하면 이쪽 좌표도 자동으로 바뀝니다.)")

        st.markdown("#### 3) 추가 상세 정보")
        phone = st.text_input("☎ 전화번호 (선택)")
        url = st.text_input("🔗 링크 (인스타, 네이버플레이스 등)", value="")
        price_range = st.selectbox(
            "💰 가격대 (선택)",
            ["선택 안 함", "₩ (저렴)", "₩₩ (보통)", "₩₩₩ (조금 비쌈)", "₩₩₩₩ (매우 비쌈)"],
            index=0,
        )
        rating = st.slider("⭐ 별점 (선택)", min_value=0.0, max_value=5.0, step=0.5, value=0.0)
        tags = st.text_input("🏷 태그 (쉼표로 구분, 예: 혼밥, 조용함, 디저트맛집)", value="")

        save_btn = st.button("✅ 이 정보로 맛집 저장하기")

        if save_btn:
            if not name:
                st.error("맛집 이름은 꼭 입력해야 합니다!")
            else:
                price_value = "" if price_range == "선택 안 함" else price_range
                rating_value = None if rating == 0.0 else rating

                add_restaurant(
                    conn,
                    name=name,
                    category=category,
                    memo=memo,
                    lat=float(st.session_state["lat"]),
                    lon=float(st.session_state["lon"]),
                    address=address,
                    phone=phone,
                    url=url,
                    price_range=price_value,
                    rating=rating_value,
                    tags=tags,
                )
                st.success(f"'{name}' 맛집이 저장되었습니다 ✅")

    st.markdown("---")
    st.markdown("### 📃 저장된 맛집 리스트")

    df = load_restaurants(conn)

    if df.empty:
        st.info("아직 저장된 맛집이 없습니다.")
    else:
        # 간단한 필터 (카테고리 / 태그)
        with st.expander("🔍 리스트 필터/정렬 옵션"):
            cat_options = ["전체"] + sorted([c for c in df["category"].dropna().unique().tolist() if c])
            selected_cat = st.selectbox("카테고리 필터", cat_options)

            tag_keyword = st.text_input("태그/이름/메모 검색 (부분 포함 검색)", value="")

            sort_option = st.selectbox(
                "정렬 기준",
                ["최근 저장 순", "별점 높은 순"],
                index=0
            )

        filtered = df.copy()
        if selected_cat != "전체":
            filtered = filtered[filtered["category"] == selected_cat]

        if tag_keyword.strip():
            kw = tag_keyword.strip()
            mask = (
                filtered["name"].astype(str).str.contains(kw, case=False) |
                filtered["tags"].astype(str).str.contains(kw, case=False) |
                filtered["memo"].astype(str).str.contains(kw, case=False)
            )
            filtered = filtered[mask]

        if sort_option == "별점 높은 순":
            filtered = filtered.sort_values(["rating", "created_at"], ascending=[False, False])

        for _, row in filtered.iterrows():
            with st.container():
                title_line = row["name"]
                if row["category"]:
                    title_line += f"  ({row['category']})"
                st.markdown(f"#### 🍴 {title_line}")

                # 주소/위치
                if isinstance(row.get("address"), str) and row["address"].strip():
                    st.markdown(f"- **📍 주소**: {row['address']}")
                st.markdown(f"- **🗺 좌표**: {row['lat']:.6f}, {row['lon']:.6f}")

                # 전화 / 가격 / 별점
                if isinstance(row.get("phone"), str) and row["phone"].strip():
                    st.markdown(f"- **☎ 전화번호**: {row['phone']}")
                if isinstance(row.get("price_range"), str) and row["price_range"].strip():
                    st.markdown(f"- **💰 가격대**: {row['price_range']}")
                if pd.notna(row.get("rating")):
                    st.markdown(f"- **⭐ 별점**: {row['rating']:.1f} / 5.0")

                # 태그
                if isinstance(row.get("tags"), str) and row["tags"].strip():
                    st.markdown(f"- **🏷 태그**: {row['tags']}")

                # 메모
                if isinstance(row.get("memo"), str) and row["memo"].strip():
                    st.markdown(f"- **📝 메모**: {row['memo']}")

                # 링크
                if isinstance(row.get("url"), str) and row["url"].strip():
                    st.markdown(f"- **🔗 링크**: [바로가기]({row['url']})")

                st.caption(f"저장 시각: {row['created_at']}")

                col_del, _ = st.columns([1, 5])
                with col_del:
                    if st.button("🗑 삭제", key=f"delete_{row['id']}"):
                        delete_restaurant(conn, int(row["id"]))
                        st.experimental_rerun()

                st.markdown("---")

# ==========================================
# 오른쪽: 지도 (클릭해서 위치 선택 가능)
# ==========================================
with right_col:
    st.markdown("### 🗺 내 맛집 지도 (클릭해서 위치 찍기)")

    df_all = load_restaurants(conn)

    # 지도 기본 중심
    center_lat = st.session_state.get("lat", 37.566535)
    center_lon = st.session_state.get("lon", 126.977969)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=13)

    # 기존 맛집들 마커로 표시
    if not df_all.empty:
        for _, row in df_all.iterrows():
            popup_text = f"{row['name']}"
            if isinstance(row.get("category"), str) and row["category"].strip():
                popup_text += f" ({row['category']})"
            if isinstance(row.get("rating"), float) and pd.notna(row["rating"]):
                popup_text += f" ⭐{row['rating']:.1f}"
            folium.Marker(
                [row["lat"], row["lon"]],
                popup=popup_text,
                tooltip=popup_text,
            ).add_to(m)

    # 사용자가 선택한 위치 마커
    folium.Marker(
        [center_lat, center_lon],
        popup="현재 선택된 위치",
        tooltip="현재 선택된 위치",
        icon=folium.Icon(icon="star"),
    ).add_to(m)

    map_data = st_folium(m, height=500, width="100%")

    # 지도 클릭 시 좌표 업데이트
    if map_data and map_data.get("last_clicked") is not None:
        clicked = map_data["last_clicked"]
        clicked_lat = clicked["lat"]
        clicked_lon = clicked["lng"]
        st.session_state["lat"] = float(clicked_lat)
        st.session_state["lon"] = float(clicked_lon)
        st.info(f"지도를 클릭해서 위치를 선택했습니다: lat={clicked_lat:.6f}, lon={clicked_lon:.6f}")
