import string
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, HttpUrl
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Index
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
import redis

# ----------------- Database & Cache Setup -----------------
DATABASE_URL = "sqlite:///./shortener.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Local Redis client
cache = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

# ----------------- Models -----------------
class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, index=True)
    original_url = Column(String, nullable=False)
    slug = Column(String(10), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    clicks = relationship("ClickEvent", back_populates="link", cascade="all, delete-orphan")


class ClickEvent(Base):
    __tablename__ = "click_events"

    id = Column(Integer, primary_key=True, index=True)
    link_id = Column(Integer, ForeignKey("links.id"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_agent = Column(String, nullable=True)
    referrer = Column(String, nullable=True)

    link = relationship("Link", back_populates="clicks")


Base.metadata.create_all(bind=engine)

# ----------------- Utilities -----------------
BASE62 = string.digits + string.ascii_letters  # 0-9, a-z, A-Z (length 62)

def encode_base62(num: int) -> str:
    """Converts a positive integer ID into a Base62 alphanumeric slug."""
    if num == 0:
        return BASE62[0]
    chars = []
    base = len(BASE62)
    while num > 0:
        num, rem = divmod(num, base)
        chars.append(BASE62[rem])
    return "".join(reversed(chars))

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----------------- Schemas -----------------
class ShortenRequest(BaseModel):
    url: HttpUrl

class ShortenResponse(BaseModel):
    slug: str
    short_url: str
    original_url: str

class AnalyticsResponse(BaseModel):
    slug: str
    original_url: str
    total_clicks: int
    recent_referrers: list[Optional[str]]
    created_at: datetime

# ----------------- FastAPI App -----------------
app = FastAPI(
    title="URL Shortener & Analytics API",
    description="High-performance URL redirect service with Base62 slugs and Redis caching.",
    version="1.0.0"
)

@app.post("/api/links", response_model=ShortenResponse, status_code=status.HTTP_201_CREATED)
def create_short_link(payload: ShortenRequest, request: Request, db: Session = Depends(get_db)):
    """Creates a shortened URL using the record's auto-incrementing ID for collision-free Base62 slugs."""
    raw_url = str(payload.url)

    # 1. Insert placeholder record to generate auto-increment ID
    link = Link(original_url=raw_url)
    db.add(link)
    db.commit()
    db.refresh(link)

    # 2. Encode unique ID to Base62 slug
    slug = encode_base62(link.id)
    link.slug = slug
    db.commit()

    # 3. Warm the cache (1 hour TTL)
    cache.setex(f"slug:{slug}", 3600, raw_url)

    base_url = str(request.base_url).rstrip("/")
    return {
        "slug": slug,
        "short_url": f"{base_url}/{slug}",
        "original_url": raw_url
    }

@app.get("/{slug}", response_class=RedirectResponse, status_code=status.HTTP_302_FOUND)
def redirect_to_url(slug: str, request: Request, db: Session = Depends(get_db)):
    """Redirects to target URL. Checks Redis first; falls back to SQLite on cache miss."""
    # 1. Check Redis cache
    target_url = cache.get(f"slug:{slug}")
    link_id = None

    if not target_url:
        # 2. Cache miss -> query SQLite
        link = db.query(Link).filter(Link.slug == slug).first()
        if not link:
            raise HTTPException(status_code=404, detail="Short URL not found")
        
        target_url = link.original_url
        link_id = link.id
        # Populate cache
        cache.setex(f"slug:{slug}", 3600, target_url)
    else:
        # Retrieve link ID for event logging
        link_id_val = cache.get(f"id:{slug}")
        if link_id_val:
            link_id = int(link_id_val)
        else:
            link = db.query(Link.id).filter(Link.slug == slug).first()
            if link:
                link_id = link[0]
                cache.setex(f"id:{slug}", 3600, link_id)

    # 3. Log access metadata asynchronously or synchronously
    if link_id:
        click = ClickEvent(
            link_id=link_id,
            user_agent=request.headers.get("user-agent"),
            referrer=request.headers.get("referer")
        )
        db.add(click)
        db.commit()

    return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)

@app.get("/api/links/{slug}/analytics", response_model=AnalyticsResponse)
def get_link_analytics(slug: str, db: Session = Depends(get_db)):
    """Retrieves access metrics for a specific slug."""
    link = db.query(Link).filter(Link.slug == slug).first()
    if not link:
        raise HTTPException(status_code=404, detail="Short URL not found")

    clicks = link.clicks
    return {
        "slug": link.slug,
        "original_url": link.original_url,
        "total_clicks": len(clicks),
        "recent_referrers": [c.referrer for c in clicks[-5:] if c.referrer],
        "created_at": link.created_at
    }