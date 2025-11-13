import streamlit as st
import sqlite3
import pandas as pd

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
# Streamlit UI
# ------------------------
st.set_page_config(
    page_title="나만의 맛집 지도",
    layout="wide",
)

st.title("🍽️ 나만의 맛집 지도")
st.caption("내가 찍은 맛집의 위치와 상세정보를 서버에 저장하고, 언제든지 꺼내 보기 ✨")

conn = get_connection()

# ------------------------
# 좌측: 맛집 추가 폼
# ------------------------
st.sidebar.header("➕ 맛집 추가하기")

with st.sidebar.form("add_form", clear_on_submit=True):
    st.markdown("### 기본 정보")
    name = st.text_input("맛집 이름 *")
    category = st.text_input("카테고리 (예: 한식, 카페, 라멘 등)", value="")
    memo = st.text_area("메모 (추천 메뉴, 분위기 등)", height=80)

    st.markdown("### 📍 위치 (위도, 경도 직접 입력)")
    col_lat, col_lon = st.columns(2)
    with col_lat:
        lat = st.number_input("위도 (lat)", format="%.6f", value=37.566535)
    with col_lon:
        lon = st.number_input("경도 (lon)", format="%.6f", value=126.977969)

    st.markdown("### 📌 상세 정보")
    address = st.text_input("주소 (선택)")
    phone = st.text_input("전화번호 (선택)")
    url = st.text_input("링크 (인스타, 네이버플레이스 등)", value="")
    price_range = st.selectbox(
        "가격대 (선택)",
        ["선택 안 함", "₩ (저렴)", "₩₩ (보통)", "₩₩₩ (조금 비쌈)", "₩₩₩₩ (매우 비쌈)"],
        index=0,
    )
    rating = st.slider("별점 (선택)", min_value=0.0, max_value=5.0, step=0.5, value=0.0)
    tags = st.text_input("태그 (쉼표로 구분, 예: 혼밥, 조용함, 디저트맛집)", value="")

    submitted = st.form_submit_button("저장하기")

    if submitted:
        if not name:
            st.error("맛집 이름은 꼭 입력해야 합니다!")
        else:
            # '선택 안 함'은 빈 문자열로 저장
            price_value = "" if price_range == "선택 안 함" else price_range
            rating_value = None if rating == 0.0 else rating

            add_restaurant(
                conn,
                name,
                category,
                memo,
                float(lat),
                float(lon),
                address,
                phone,
                url,
                price_value,
                rating_value,
                tags,
            )
            st.success(f"'{name}' 맛집이 저장되었습니다 ✅")

# ------------------------
# 우측: 데이터 조회
# ------------------------
tab_map, tab_list = st.tabs(["🗺 지도 보기", "📃 리스트 보기"])

df = load_restaurants(conn)

with tab_map:
    st.subheader("🗺 저장된 맛집 지도")

    if df.empty:
        st.info("아직 저장된 맛집이 없습니다. 왼쪽에서 새로운 맛집을 추가해 보세요!")
    else:
        # Streamlit map을 위한 컬럼 이름 맞추기
        map_df = df.rename(columns={"lat": "latitude", "lon": "longitude"})
        st.map(map_df[["latitude", "longitude"]])

        with st.expander("📍 맛집 목록 간단히 보기"):
            st.dataframe(
                df[
                    [
                        "id",
                        "name",
                        "category",
                        "address",
                        "lat",
                        "lon",
                        "rating",
                        "created_at",
                    ]
                ]
            )

with tab_list:
    st.subheader("📃 저장된 맛집 리스트")

    if df.empty:
        st.info("아직 저장된 맛집이 없습니다.")
    else:
        for _, row in df.iterrows():
            with st.container():
                title_line = row["name"]
                if row["category"]:
                    title_line += f"  ({row['category']})"
                st.markdown(f"### {title_line}")

                # 위치
                st.markdown(f"- **위치(위도,경도)**: {row['lat']:.6f}, {row['lon']:.6f}")

                # 주소
                if row.get("address"):
                    if isinstance(row["address"], str) and row["address"].strip():
                        st.markdown(f"- **주소**: {row['address']}")

                # 전화번호
                if row.get("phone"):
                    if isinstance(row["phone"], str) and row["phone"].strip():
                        st.markdown(f"- **전화번호**: {row['phone']}")

                # 가격대
                if row.get("price_range"):
                    if isinstance(row["price_range"], str) and row["price_range"].strip():
                        st.markdown(f"- **가격대**: {row['price_range']}")

                # 별점
                if pd.notna(row.get("rating")):
                    st.markdown(f"- **별점**: ⭐ {row['rating']:.1f} / 5.0")

                # 태그
                if row.get("tags"):
                    if isinstance(row["tags"], str) and row["tags"].strip():
                        st.markdown(f"- **태그**: {row['tags']}")

                # 메모
                if row["memo"]:
                    st.markdown(f"- **메모**: {row['memo']}")

                # 링크
                if row.get("url"):
                    if isinstance(row["url"], str) and row["url"].strip():
                        st.markdown(f"- **링크**: [바로가기]({row['url']})")

                st.caption(f"저장 시각: {row['created_at']}")

                col1, col2 = st.columns([1, 4])
                with col1:
                    if st.button("삭제", key=f"delete_{row['id']}"):
                        delete_restaurant(conn, int(row["id"]))
                        st.experimental_rerun()
                st.markdown("---")
