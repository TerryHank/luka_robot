"""Small, persistent object inventory; no model, camera, or motion dependencies.

An entity is an *estimated identity*, not a guarantee that a physical object has
not been replaced. Coordinates are supplied by the capture worker; this module
never turns an observation pose into an object position.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path


# Kept independent of yoloe_bridge so a database query does not import OpenCV.
_LABELS = {
    "sofa": "沙发", "chair": "椅子", "table": "桌子", "desk": "书桌",
    "bed": "床", "cabinet": "柜子", "wardrobe": "衣柜", "bookshelf": "书架",
    "nightstand": "床头柜", "stool": "凳子", "bench": "长凳",
    "refrigerator": "冰箱", "microwave": "微波炉", "oven": "烤箱", "stove": "灶台",
    "washing machine": "洗衣机", "dryer": "烘干机", "air conditioner": "空调",
    "fan": "风扇", "television": "电视", "computer": "电脑", "monitor": "显示器",
    "printer": "打印机", "vacuum cleaner": "吸尘器", "bottle": "瓶子",
    "cup": "杯子", "mug": "马克杯", "glass": "玻璃杯", "bowl": "碗", "plate": "盘子",
    "fork": "叉子", "knife": "刀", "spoon": "勺子", "kettle": "水壶", "pot": "锅",
    "pan": "平底锅", "cutting board": "砧板", "toaster": "烤面包机", "rice cooker": "电饭锅",
    "toilet": "马桶", "sink": "水槽", "bathtub": "浴缸", "shower": "淋浴",
    "mirror": "镜子", "towel": "毛巾", "soap": "肥皂", "toothbrush": "牙刷",
    "toothpaste": "牙膏", "tissue": "纸巾", "scissors": "剪刀", "wire": "电线",
    "book": "书", "bag": "包", "backpack": "背包", "keys": "钥匙", "wallet": "钱包",
    "phone": "手机", "remote control": "遥控器", "clock": "时钟", "umbrella": "雨伞",
    "shoe": "鞋", "clothes": "衣服", "pillow": "枕头", "blanket": "被子",
    "trash can": "垃圾桶", "door": "门", "window": "窗户", "curtain": "窗帘",
    "light": "灯", "fire extinguisher": "灭火器",
}
_ALIASES = {value: key for key, value in _LABELS.items()}
_ALIASES.update({
    "办公椅": "chair", "餐桌": "table", "办公桌": "desk", "橱柜": "cabinet",
    "储物柜": "cabinet", "冰柜": "refrigerator", "炉子": "stove", "电风扇": "fan",
    "电视机": "television", "台式机": "computer", "水瓶": "bottle",
    "水杯": "cup", "烧水壶": "kettle",
    "洗手池": "sink", "花洒": "shower", "香皂": "soap", "线缆": "wire", "网线": "wire",
    "电话": "phone", "钟": "clock", "伞": "umbrella", "鞋子": "shoe", "衣物": "clothes",
    "毯子": "blanket", "窗": "window", "灯具": "light", "couch": "sofa", "fridge": "refrigerator",
    "tv": "television", "cell phone": "phone", "dining table": "table", "potted plant": "plant",
})
_COLORS = {"红": "红色", "橙": "橙色", "黄": "黄色", "绿": "绿色", "蓝": "蓝色",
           "紫": "紫色", "粉": "粉色", "棕": "棕色", "褐": "棕色", "黑": "黑色",
           "白": "白色", "灰": "灰色"}
_COLOR_EN = dict(zip(
    ("red", "orange", "yellow", "green", "blue", "purple", "pink", "brown", "black", "white", "gray", "grey"),
    ("红色", "橙色", "黄色", "绿色", "蓝色", "紫色", "粉色", "棕色", "黑色", "白色", "灰色", "灰色")))
_COLOR_ALIASES = {"褐色": "棕色", "棕褐色": "棕色", "棕褐": "棕色"}
_DESCRIPTORS = {"细长", "圆形", "长方形", "方形", "扁平", "高", "矮", "大", "小"}
_PEOPLE = {"person", "people", "human", "man", "woman", "child", "人", "行人", "男人", "女人", "小孩"}


def _number_list(value, length=None):
    if not isinstance(value, (list, tuple)) or (length and len(value) != length):
        return None
    try:
        values = [float(v) for v in value]
    except (TypeError, ValueError):
        return None
    return values if values and len(values) <= 512 and all(math.isfinite(v) for v in values) else None


def _iou(a, b):
    if not a or not b:
        return 0.0
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return None
    norm = math.sqrt(sum(v * v for v in a) * sum(v * v for v in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm > 0 else None


def _same_view(a, b):
    """Only compare unpositioned crops when camera viewpoints nearly coincide."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    ap, bp = _number_list(a.get("translation"), 3), _number_list(b.get("translation"), 3)
    aq, bq = _number_list(a.get("quaternion_xyzw"), 4), _number_list(b.get("quaternion_xyzw"), 4)
    if not all((ap, bp, aq, bq)) or math.dist(ap, bp) >= .10:
        return False
    na, nb = math.sqrt(sum(x * x for x in aq)), math.sqrt(sum(x * x for x in bq))
    if abs(na - 1) > .01 or abs(nb - 1) > .01:
        return False
    # Full orientation is stricter than yaw alone and handles q and -q.
    angle = 2 * math.acos(min(1.0, abs(sum(x * y for x, y in zip(aq, bq))) / (na * nb)))
    return angle < .08


def _label(value):
    value = str(value or "").strip().lower()
    return _ALIASES.get(value, value)


def _colors(values):
    if not isinstance(values, (tuple, list)):
        return []
    result = []
    for value in values:
        value = str(value).strip().lower()
        value = _COLOR_ALIASES.get(value, _COLOR_EN.get(value, _COLORS.get(value, value)))
        if value in _COLORS.values() and value not in result:
            result.append(value)
    return result[:3]


class SemanticStore:
    """SQLite object entities with bounded, sampled evidence history.

    root is the database directory. Ingest is a single camera frame; call it at
    most once per distinct capture timestamp. Unconfirmed candidates and stale
    observation-only tracks are never silently promoted to positioned objects.
    """

    CONFIRM_SIGHTINGS = 3
    TRACK_TTL = 2.5
    MAP_MATCH_METERS = 0.35
    HISTORY_LIMIT = 20
    HISTORY_INTERVAL = 5.0

    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "entities.sqlite3"
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL,
                    map_id TEXT NOT NULL, floor_id TEXT NOT NULL,
                    last_seen REAL NOT NULL, confirmed INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS entities_scope ON entities(map_id, floor_id, label);
                CREATE TABLE IF NOT EXISTS observations (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_id TEXT NOT NULL, captured_at REAL NOT NULL,
                    payload TEXT NOT NULL,
                    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS observations_entity ON observations(entity_id, seq);
                CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, last_frame REAL NOT NULL);
            """)

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(str(self.db), timeout=10)
        try:
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _public(entity):
        return {k: v for k, v in entity.items() if not k.startswith("_")}

    @staticmethod
    def _normalize(detection):
        label = _label(detection.get("label"))
        if not label or label in _PEOPLE:
            return None
        try:
            score = float(detection.get("score", 0))
        except (ValueError, TypeError):
            return None
        if not math.isfinite(score) or not 0 <= score <= 1:
            return None
        box = _number_list(detection.get("box_rgb"), 4)
        if box and (box[2] <= box[0] or box[3] <= box[1]):
            box = None
        point = _number_list(detection.get("map_xyz_m"), 3)
        return dict(detection, label=label, score=score, box_rgb=box,
                    map_xyz_m=point, colors=_colors(detection.get("colors", [])),
                    appearance=_number_list(detection.get("appearance")),
                    descriptors=[v for v in (detection.get("descriptors") or []) if v in _DESCRIPTORS])

    def _match(self, detection, entity, timestamp, session):
        """Return (cost, uncertain), or None when there is no safe association."""
        if detection["label"] != entity["label"]:
            return None
        similarity = _cosine(detection.get("appearance"), entity.get("_appearance"))
        # Strong appearance/color disagreement wins over a nearby map point.
        if similarity is not None and similarity < 0.78:
            return None
        colors, old_colors = set(detection["colors"]), set(entity.get("colors", []))
        if colors and old_colors and not colors.intersection(old_colors):
            return None
        temporal = entity.get("_session_id") == session and 0 < timestamp - entity["last_seen"] <= self.TRACK_TTL
        overlap = _iou(detection.get("box_rgb"), entity.get("_box_rgb")) if temporal else 0.0
        point, old_point = detection.get("map_xyz_m"), entity.get("map_xyz_m") or entity.get("last_known_map_xyz_m")
        if point and old_point:
            distance = math.dist(point, old_point)
            if distance > self.MAP_MATCH_METERS:
                return None
            # During one pass image overlap disambiguates neighbors. Across
            # passes weak evidence only supports a much tighter map match.
            appearance_supported = similarity is not None and similarity >= 0.90
            if not temporal and not appearance_supported and distance > 0.18:
                return None
            return distance / self.MAP_MATCH_METERS + (1 - overlap) * 0.45, not temporal and not appearance_supported
        # No position: a recently tracked box is useful, but cannot establish
        # identity in another session or after the object leaves the view.
        if temporal and overlap >= 0.35:
            return 1.0 - overlap, False
        # A comparable view can reconnect an object with invalid depth without
        # claiming a 3D position. Even strong crop agreement is not conclusive
        # physical identity, so keep an uncertainty flag for the caller.
        same_view_overlap = _iou(detection.get("box_rgb"), entity.get("_box_rgb"))
        if (similarity is not None and similarity >= .96 and same_view_overlap >= .65
                and _same_view(detection.get("observation_pose"), entity.get("observation_pose"))):
            return 1.0 - same_view_overlap + .2, True
        return None

    def ingest(self, detections, context, captured_at, session_id):
        timestamp = float(captured_at)
        if not math.isfinite(timestamp) or timestamp <= 0:
            raise ValueError("captured_at must be a positive, finite timestamp")
        session = str(session_id).strip()
        if not session or len(session) > 200:
            raise ValueError("session_id is required")
        map_id = str(context.get("map_id") or "unknown")
        floor_id = str(context.get("floor_id") or context.get("floor") or "unknown")
        normalized = [self._normalize(d) for d in detections if isinstance(d, dict)]
        normalized = [d for d in normalized if d is not None]
        for detection in normalized:
            if not detection.get("observation_pose"):
                detection["observation_pose"] = context.get("map_from_base")
        with self._lock, self._connect() as db:
            previous = db.execute("SELECT last_frame FROM sessions WHERE id=?", (session,)).fetchone()
            if previous and timestamp <= previous[0]:
                return []
            db.execute("INSERT OR REPLACE INTO sessions VALUES (?, ?)", (session, timestamp))
            # Session bookkeeping and unconfirmed false positives are bounded
            # in time; confirmed object memories are retained until removed.
            db.execute("DELETE FROM sessions WHERE last_frame < ?", (timestamp - 7 * 86400,))
            db.execute("DELETE FROM entities WHERE confirmed=0 AND last_seen < ?", (timestamp - 86400,))
            rows = db.execute("SELECT payload FROM entities WHERE map_id=? AND floor_id=?", (map_id, floor_id)).fetchall()
            candidates = [json.loads(row[0]) for row in rows]
            by_id = {e["id"]: e for e in candidates}
            edges = []
            ambiguous = set()
            for index, detection in enumerate(normalized):
                choices = []
                for entity in candidates:
                    match = self._match(detection, entity, timestamp, session)
                    if match:
                        choices.append((match[0], index, entity["id"], match[1]))
                choices.sort()
                if len(choices) > 1 and choices[1][0] - choices[0][0] < 0.12:
                    # An ambiguous new track must be able to continue on the
                    # next frame. Prefer it only when it is the unique newest
                    # candidate and its image overlap is strong; equal-age
                    # neighboring objects remain ambiguous.
                    newest = max(by_id[c[2]]["last_seen"] for c in choices)
                    latest = [c for c in choices if by_id[c[2]]["last_seen"] == newest]
                    if len(latest) == 1:
                        recent = by_id[latest[0][2]]
                        temporal = recent.get("_session_id") == session and 0 < timestamp - newest <= self.TRACK_TTL
                        if temporal and _iou(detection.get("box_rgb"), recent.get("_box_rgb")) >= .65:
                            edges.append(latest[0])
                        else:
                            ambiguous.add(index)
                    else:
                        ambiguous.add(index)
                else:
                    edges.extend(choices)
            # A given old entity can accept only one detection from this frame.
            assigned, used = {}, set()
            for cost, index, entity_id, uncertain in sorted(edges):
                if index not in assigned and entity_id not in used:
                    assigned[index] = (by_id[entity_id], uncertain)
                    used.add(entity_id)
            result = []
            for index, detection in enumerate(normalized):
                matched = assigned.get(index)
                if matched:
                    entity, uncertain = matched
                    consecutive = entity.get("_consecutive", 1) + 1 if (
                        entity.get("_session_id") == session and timestamp - entity["last_seen"] <= self.TRACK_TTL
                    ) else 1
                    entity["seen_count"] += 1
                else:
                    uncertain = index in ambiguous
                    consecutive = 1
                    entity = {
                        "id": "obj_" + uuid.uuid4().hex[:16], "label": detection["label"],
                        "name_zh": _LABELS.get(detection["label"], detection["label"]),
                        "map_id": map_id, "floor_id": floor_id,
                        "first_seen": timestamp, "seen_count": 1, "confirmed": False,
                    }
                old_history_time = entity.get("_history_time", 0)
                previous_confirmed = entity["confirmed"]
                entity.update({
                    "last_seen": timestamp, "score": detection["score"],
                    "confirmed": entity["confirmed"] or consecutive >= self.CONFIRM_SIGHTINGS,
                    "identity_uncertain": bool(entity.get("identity_uncertain") or uncertain),
                    "colors": detection["colors"] or entity.get("colors", []),
                    "descriptors": detection["descriptors"] or entity.get("descriptors", []),
                    "observation_pose": detection.get("observation_pose") or context.get("map_from_base"),
                    "area_hint": detection.get("area_hint") or context.get("area_hint") or entity.get("area_hint"),
                    "room": detection.get("room") or context.get("room") or entity.get("room"),
                    "evidence_url": detection.get("evidence_url") or entity.get("evidence_url"),
                    "_box_rgb": detection.get("box_rgb"), "_session_id": session,
                    "_consecutive": consecutive,
                    "_appearance": detection.get("appearance") or entity.get("_appearance"),
                })
                # If the current sighting lacks depth, do not label an old map
                # point as this sighting's location. Retain it explicitly as
                # historical information instead of claiming a fresh position.
                if entity.get("map_xyz_m") and not detection["map_xyz_m"]:
                    entity["last_known_map_xyz_m"] = entity["map_xyz_m"]
                    entity["last_position_at"] = entity.get("position_at")
                entity["map_xyz_m"] = detection["map_xyz_m"]
                entity["position_at"] = timestamp if detection["map_xyz_m"] else None
                entity["position_status"] = (detection.get("position_status") or "estimated") if detection["map_xyz_m"] else "observation_only"
                entity["description"] = "、".join(entity["colors"] + entity["descriptors"]) + ("的" if entity["colors"] or entity["descriptors"] else "") + entity["name_zh"]
                keep_history = timestamp - old_history_time >= self.HISTORY_INTERVAL or not matched or entity["confirmed"] != previous_confirmed
                if keep_history:
                    entity["_history_time"] = timestamp
                payload = json.dumps(entity, ensure_ascii=False, allow_nan=False)
                db.execute("""INSERT INTO entities VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET label=excluded.label,
                           map_id=excluded.map_id, floor_id=excluded.floor_id,
                           last_seen=excluded.last_seen, confirmed=excluded.confirmed,
                           payload=excluded.payload""",
                           (entity["id"], entity["label"], map_id, floor_id, timestamp, int(entity["confirmed"]), payload))
                if keep_history:
                    db.execute("INSERT INTO observations(entity_id, captured_at, payload) VALUES (?, ?, ?)",
                               (entity["id"], timestamp, json.dumps(self._public(entity), ensure_ascii=False, allow_nan=False)))
                    db.execute("DELETE FROM observations WHERE entity_id=? AND seq NOT IN (SELECT seq FROM observations WHERE entity_id=? ORDER BY seq DESC LIMIT ?)",
                               (entity["id"], entity["id"], self.HISTORY_LIMIT))
                result.append(self._public(entity))
            return result

    def set_evidence(self, entity_id, url):
        """Attach the worker's bounded per-entity image after it has an ID."""
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM entities WHERE id=?", (str(entity_id),)).fetchone()
            if not row:
                return False
            entity = json.loads(row[0])
            entity["evidence_url"] = str(url) if url else None
            db.execute("UPDATE entities SET payload=? WHERE id=?",
                       (json.dumps(entity, ensure_ascii=False, allow_nan=False), str(entity_id)))
            return True

    @staticmethod
    def _query(query):
        text = str(query or "").strip().lower()
        if not text:
            return None, set(), set()
        labels = []
        # Longest match prevents 床 from consuming 床头柜, 包 from consuming 背包.
        aliases = dict(_ALIASES, **{k: k for k in _LABELS})
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = re.escape(alias) if not alias.isascii() else r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])"
            if re.search(pattern, text):
                labels.append(aliases[alias])
                text = re.sub(pattern, " ", text)
        colors = set()
        for term, canonical in sorted({**_COLORS, **_COLOR_EN, **_COLOR_ALIASES, **{c: c for c in _COLORS.values()}}.items(), key=lambda p: len(p[0]), reverse=True):
            pattern = re.escape(term) if not term.isascii() else r"(?<![a-z])" + re.escape(term) + r"(?![a-z])"
            if re.search(pattern, text):
                colors.add(canonical)
                text = re.sub(pattern, " ", text)
        descriptors = set()
        for term in sorted(_DESCRIPTORS, key=len, reverse=True):
            if term in text:
                descriptors.add(term)
                text = text.replace(term, " ")
        for filler in ("请帮我找到", "请帮我找", "帮我找到", "帮我找", "给我找", "在哪里", "在哪儿", "在什么位置", "的位置", "带我去找", "带我去", "找到", "查找", "搜索", "我要找", "我想找", "那个", "这个", "一个", "一只", "一把", "那只", "这只", "哪里", "在哪", "寻找", "的", "找", "请", "呢", "吗"):
            text = text.replace(filler, " ")
        text = re.sub(r"\b(?:find|where|is|are|the|a|an|please|my)\b", " ", text)
        # Unsupported attributes (brand, material, etc.) must not become a
        # confident result for merely the recognized category.
        if re.sub(r"[\s，。！？、,.;:!?\-_/]+", "", text) or not labels or len(set(labels)) != 1:
            return False, colors, descriptors
        return set(labels), colors, descriptors

    def search(self, query="", map_id=None, include_tentative=False, limit=50):
        labels, colors, descriptors = self._query(query)
        if labels is False:
            return []
        limit = max(1, min(int(limit), 500))
        conditions, params = [], []
        if not include_tentative:
            conditions.append("confirmed=1")
        if map_id is not None:
            conditions.append("map_id=?")
            params.append(str(map_id))
        if labels:
            conditions.append("label=?")
            params.append(next(iter(labels)))
        sql = "SELECT payload FROM entities" + (" WHERE " + " AND ".join(conditions) if conditions else "") + " ORDER BY last_seen DESC"
        result = []
        with self._lock, self._connect() as db:
            for row in db.execute(sql, params):
                entity = json.loads(row[0])
                if not colors.issubset(entity.get("colors", [])) or not descriptors.issubset(entity.get("descriptors", [])):
                    continue
                result.append(self._public(entity))
                if len(result) >= limit:
                    break
        return result

    def stats(self):
        with self._lock, self._connect() as db:
            count, confirmed = db.execute("SELECT COUNT(*), COALESCE(SUM(confirmed), 0) FROM entities").fetchone()
            history = db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
            last_seen = db.execute("SELECT MAX(last_seen) FROM entities").fetchone()[0]
        return {"entities": count, "confirmed": confirmed, "tentative": count - confirmed,
                "observations": history, "last_seen": last_seen,
                "confirmation_sightings": self.CONFIRM_SIGHTINGS,
                "history_limit_per_entity": self.HISTORY_LIMIT}
