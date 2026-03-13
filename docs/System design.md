# WhatsApp Web Clone — Complete System Design

## PHASE 1: SYSTEM ARCHITECTURE

---

### 1.1 High-Level Architecture Diagram

```
                        ┌─────────────────────────────────────────────────────────┐
                        │                    CLIENTS                              │
                        │   [Browser/React]     [Mobile App]    [Desktop App]     │
                        └────────────────────────────┬────────────────────────────┘
                                                     │ HTTPS / WSS
                                                     ▼
                        ┌─────────────────────────────────────────────────────────┐
                        │                  NGINX (Reverse Proxy)                  │
                        │         - SSL Termination  - Load Balancing             │
                        │         - Static Files     - Rate Limiting              │
                        └────────────┬────────────────────────┬───────────────────┘
                                     │                        │
                    ┌────────────────▼──────┐      ┌──────────▼──────────────┐
                    │   FastAPI Instance 1  │      │   FastAPI Instance 2    │
                    │   (REST + WebSocket)  │      │   (REST + WebSocket)    │
                    └────────────┬──────────┘      └──────────┬──────────────┘
                                 │                            │
                    ┌────────────▼────────────────────────────▼──────────────┐
                    │                    Redis Cluster                        │
                    │   - Pub/Sub (WebSocket cross-instance messaging)        │
                    │   - Session store                                       │
                    │   - Presence (online/offline)                           │
                    │   - Rate limiting counters                              │
                    └────────────────────────┬───────────────────────────────┘
                                             │
                    ┌────────────────────────▼───────────────────────────────┐
                    │               MongoDB Replica Set                       │
                    │   - Users   - Chats   - Messages   - Groups            │
                    └────────────────────────┬───────────────────────────────┘
                                             │
                    ┌────────────────────────▼───────────────────────────────┐
                    │              S3-Compatible Object Storage               │
                    │      (MinIO locally / AWS S3 in production)            │
                    │   - Profile pictures  - Media messages  - Documents    │
                    └────────────────────────────────────────────────────────┘
```

---

### 1.2 Component Interaction Diagram

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND COMPONENTS                              │
│                                                                          │
│  App.jsx                                                                 │
│   ├── AuthContext ──── manages JWT tokens, user state                   │
│   ├── SocketContext ── manages WebSocket lifecycle                       │
│   │                                                                      │
│   ├── Sidebar                                                            │
│   │    ├── ChatList ──── renders all conversations                      │
│   │    ├── UserSearch ── search users to start new chat                 │
│   │    └── UserProfile ─ current user info                              │
│   │                                                                      │
│   └── ChatWindow                                                         │
│        ├── MessageList ── infinite scroll, optimistic updates           │
│        ├── MessageInput ─ text, attachments, emoji                      │
│        ├── TypingBadge ── "Alice is typing..."                          │
│        └── MessageBubble ─ single message + status ticks                │
└──────────────────────────────────────────────────────────────────────────┘
                             │  REST (Axios)
                             │  WebSocket (native WS)
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          BACKEND LAYERS                                  │
│                                                                          │
│  FastAPI App                                                             │
│   ├── Middleware Layer                                                   │
│   │    ├── CORS Middleware                                               │
│   │    ├── JWT Auth Middleware                                           │
│   │    └── Request Logging Middleware                                    │
│   │                                                                      │
│   ├── Router Layer (REST)                                                │
│   │    ├── /api/v1/auth    ── login, register, refresh token            │
│   │    ├── /api/v1/users   ── profile, search, update                  │
│   │    ├── /api/v1/chats   ── create/list chats                        │
│   │    ├── /api/v1/messages── fetch history (paginated)                │
│   │    ├── /api/v1/groups  ── create, add members, leave               │
│   │    └── /api/v1/media   ── upload/download media                    │
│   │                                                                      │
│   ├── WebSocket Layer                                                    │
│   │    └── /ws/{user_id}   ── persistent WS connection per user        │
│   │                                                                      │
│   └── Service Layer                                                      │
│        ├── AuthService                                                   │
│        ├── UserService                                                   │
│        ├── ChatService                                                   │
│        ├── MessageService                                                │
│        ├── GroupService                                                  │
│        ├── PresenceService                                               │
│        └── NotificationService                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### 1.3 WebSocket Flow Diagram

```
CLIENT                    FASTAPI SERVER              REDIS PUB/SUB         OTHER INSTANCES
  │                            │                           │                      │
  │─── WSS Handshake ─────────▶│                           │                      │
  │    (with JWT token)        │                           │                      │
  │                            │── validate token          │                      │
  │                            │── register in WS manager  │                      │
  │                            │── SUBSCRIBE user channel ▶│                      │
  │                            │── publish user_online ───▶│                      │
  │◀── connection_ack ─────────│                           │── broadcast ────────▶│
  │                            │                           │                      │
  │─── join_chat ─────────────▶│                           │                      │
  │    {chat_id: "abc123"}     │── store in room map       │                      │
  │                            │                           │                      │
  │─── send_message ──────────▶│                           │                      │
  │    {chat_id, content,      │── save to MongoDB         │                      │
  │     temp_id, media_url}    │── PUBLISH to chat channel▶│                      │
  │                            │                           │── push to members ──▶│
  │◀── message_ack ────────────│                           │                      │
  │    {temp_id, real_id,      │                           │                      │
  │     timestamp, status}     │                           │                      │
  │                            │                           │                      │
  │◀── message_delivered ──────│ (when recipient connects) │                      │
  │    {message_id}            │                           │                      │
  │                            │                           │                      │
  │─── message_seen ──────────▶│                           │                      │
  │    {message_id, chat_id}   │── update status in DB     │                      │
  │                            │── PUBLISH seen event ────▶│                      │
  │                            │                           │── notify sender ────▶│
  │◀── message_seen ──── (sender's client updates ticks)   │                      │
  │                            │                           │                      │
  │─── typing ────────────────▶│                           │                      │
  │    {chat_id}               │── PUBLISH typing event ──▶│                      │
  │                            │                           │── notify others ────▶│
  │─── stop_typing ───────────▶│                           │                      │
  │                            │                           │                      │
  │─── disconnect ────────────▶│                           │                      │
  │                            │── remove from WS manager  │                      │
  │                            │── update last_seen in DB  │                      │
  │                            │── PUBLISH user_offline ──▶│                      │
  │                            │                           │── notify contacts ──▶│
```

---

### 1.4 Message Lifecycle Diagram

```
SENDER CLIENT            BACKEND                    RECIPIENT CLIENT
    │                       │                              │
    │  1. USER TYPES        │                              │
    │     [OPTIMISTIC UI]   │                              │
    │  ── Renders bubble    │                              │
    │     immediately with  │                              │
    │     temp_id + ⏳ icon │                              │
    │                       │                              │
    │  2. SEND              │                              │
    │─── send_message ─────▶│                              │
    │    {temp_id: "abc",   │                              │
    │     content: "Hello"} │                              │
    │                       │                              │
    │                       │  3. PERSIST                  │
    │                       │── Save to MongoDB            │
    │                       │   status: "sent"             │
    │                       │                              │
    │  4. ACKNOWLEDGE       │                              │
    │◀── message_ack ───────│                              │
    │    {temp_id: "abc",   │                              │
    │     real_id: "xyz",   │                              │
    │     status: "sent"}   │                              │
    │  ── Replace ⏳ with ✓ │                              │
    │                       │                              │
    │                       │  5. DELIVER                  │
    │                       │── Push via WebSocket ───────▶│
    │                       │   or push notification       │
    │                       │   if offline                 │
    │                       │                              │
    │                       │  6. DELIVERED ACK            │
    │                       │◀─────────────────────────────│
    │                       │── Update status: "delivered" │
    │  7. DELIVERED         │                              │
    │◀── message_delivered ─│                              │
    │  ── Show ✓✓ (grey)    │                              │
    │                       │                              │
    │                       │  8. SEEN                     │
    │                       │◀─ message_seen ──────────────│
    │                       │   (when user opens chat)     │
    │                       │── Update status: "seen"      │
    │  9. SEEN              │                              │
    │◀── message_seen ──────│                              │
    │  ── Show ✓✓ (blue)    │                              │
```

---

### 1.5 Database ER Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           ENTITY RELATIONSHIPS                          │
│                                                                         │
│  ┌──────────────┐         ┌──────────────┐         ┌────────────────┐  │
│  │    Users     │         │    Chats     │         │    Groups      │  │
│  ├──────────────┤         ├──────────────┤         ├────────────────┤  │
│  │ _id (ObjId)  │◀────────│participants[]│         │ _id (ObjId)    │  │
│  │ phone        │         │ _id (ObjId)  │────────▶│ name           │  │
│  │ username     │         │ type (1-1/   │         │ description    │  │
│  │ password_hash│         │   group)     │         │ avatar_url     │  │
│  │ avatar_url   │         │ group_id     │         │ created_by─────┼──┐
│  │ status       │         │ last_message │         │ members[]      │  │
│  │ last_seen    │         │ unread_count │         │  ├─ user_id    │  │
│  │ is_online    │         │ created_at   │         │  ├─ role       │  │
│  │ created_at   │         │ updated_at   │         │  └─ joined_at  │  │
│  └──────────────┘         └──────┬───────┘         └────────────────┘  │
│         ▲                        │                                      │
│         │                        │                                      │
│         │                 ┌──────▼───────┐                             │
│         │                 │   Messages   │                             │
│         │                 ├──────────────┤                             │
│         └─────────────────│ sender_id    │                             │
│                           │ _id (ObjId)  │                             │
│                           │ chat_id ─────┼─▶ Chats._id               │
│                           │ content      │                             │
│                           │ content_type │  ┌─────────────────────┐   │
│                           │   (text/img/ │  │   MessageStatus     │   │
│                           │   video/doc) │  ├─────────────────────┤   │
│                           │ media_url    │  │ _id (ObjId)         │   │
│                           │ thumbnail    │  │ message_id ─────────┼───┘
│                           │ status       │  │ user_id             │   │
│                           │ reply_to     │  │ status (delivered/  │   │
│                           │ is_deleted   │  │         seen)       │   │
│                           │ created_at   │  │ timestamp           │   │
│                           │ updated_at   │  └─────────────────────┘   │
│                           └──────────────┘                             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 1.6 Deep Dive: How Everything Works

#### Real-Time Communication Internals

FastAPI uses Starlette under the hood, which supports WebSockets natively via ASGI (Asynchronous Server Gateway Interface). Unlike HTTP, WebSocket establishes a persistent TCP connection after an HTTP upgrade handshake. Once connected, both client and server can push data at any time without polling.

We maintain a `ConnectionManager` class that holds a dictionary of `{user_id: WebSocket}`. When Server A gets a message for User B (who is connected to Server B), Server A publishes to Redis channel `chat:{chat_id}`. Server B is subscribed to that channel and pushes the message to User B's WebSocket.

#### Rooms / Chat Channels

A "room" in our system = a Redis Pub/Sub channel named `chat:{chat_id}`.

- **1-1 chats**: `chat_id` is deterministically generated from `sorted([user1_id, user2_id])` to ensure idempotency.
- **Group chats**: `chat_id` is the group's MongoDB ObjectId.

When a user opens a chat, the frontend sends `join_chat`. The server tracks which chats a user is "watching" (has open) to know when to mark messages as "seen" automatically.

#### Typing Indicators

1. Client fires `typing` event on `keydown`.
2. Server publishes `typing:{user_id}` to `chat:{chat_id}` Redis channel.
3. Other members receive it and show "Alice is typing..."
4. Client fires `stop_typing` on blur or after 3 seconds of inactivity (debounced).
5. Server publishes `stop_typing` similarly.

This is ephemeral — no DB writes. Pure Redis Pub/Sub.

#### Read Receipts (Blue Ticks)

- **Single tick (✓)**: Message saved to DB (status=`sent`).
- **Double grey tick (✓✓)**: Recipient's WebSocket received it (status=`delivered`). Triggered when we push the message to recipient.
- **Double blue tick (✓✓)**: Recipient opened the chat window and the message entered viewport (status=`seen`). Triggered by `message_seen` WS event from recipient.

In group chats: blue ticks only show when ALL members have seen the message. We store per-user status in `MessageStatus` collection.

#### Last-Seen & Online Presence

- `is_online` flag in Redis (key: `presence:{user_id}`, TTL: 30s, refreshed via heartbeat every 15s).
- On WS disconnect: Redis key expires, we update MongoDB `last_seen` timestamp.
- Contacts' presence is subscribed via Redis `user_presence:{user_id}` channel. When someone goes online/offline, we publish to that channel and all subscribed servers push to connected friends.

#### Optimistic UI Updates

1. User hits "Send".
2. Frontend immediately renders message bubble with `temp_id` and a clock icon (⏳).
3. Async: WS sends `send_message` event to server.
4. Server responds with `message_ack` containing `{temp_id, real_id, status}`.
5. Frontend swaps temp_id → real_id, updates icon from ⏳ → ✓.

If server returns error: the optimistic bubble is marked with a ❌ and retry option shown.

#### Reconnect Logic

Exponential backoff with jitter:
```
attempt 1: 1s delay
attempt 2: 2s delay
attempt 3: 4s delay
...
max: 30s delay
jitter: Math.random() * delay
```

On reconnect: client sends `sync_request` with `{last_message_id}`. Server sends back all missed messages since that ID. This ensures no message loss during brief disconnections.

#### Message Acknowledgement

Every WS event has a `message_id` (UUID). Server echoes it back in ack. If no ack received in 5s, client retries. Server is idempotent (checks if message_id already processed using Redis SET NX with TTL).

---

### 1.7 Scaling Strategy

#### Horizontal Scaling

```
                    ┌────────────────────────┐
                    │    Load Balancer        │
                    │   (sticky sessions      │
                    │   or stateless via      │
                    │   Redis session store)  │
                    └──────────┬─────────────┘
                               │
          ┌────────────────────┼────────────────────┐
          ▼                    ▼                    ▼
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │  FastAPI #1 │     │  FastAPI #2 │     │  FastAPI #3 │
   │  (N workers)│     │  (N workers)│     │  (N workers)│
   └─────────────┘     └─────────────┘     └─────────────┘
          │                    │                    │
          └────────────────────┼────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   Redis Cluster     │
                    │   (Pub/Sub + Cache) │
                    └─────────────────────┘
```

WebSockets require sticky sessions (same client → same server) OR stateless design via Redis. We use Redis — all WS state lives in Redis, so any server can handle any client.

#### Redis Pub/Sub for Multi-Instance WS

```python
# Server A receives message from User1 to User2
# User2 is connected to Server B

# Server A publishes:
redis.publish(f"chat:{chat_id}", json.dumps(event))

# Server B (subscribed to all chat channels its users are in):
async for message in redis.subscribe(f"chat:{chat_id}"):
    for user_id in local_room_members:
        await websocket_manager.send(user_id, message)
```

#### Database Indexing Strategy

```javascript
// Messages collection - most critical
db.messages.createIndex({ chat_id: 1, created_at: -1 })  // pagination
db.messages.createIndex({ sender_id: 1 })
db.messages.createIndex({ chat_id: 1, status: 1 })       // unread counts

// Users collection
db.users.createIndex({ phone: 1 }, { unique: true })
db.users.createIndex({ username: 1 })
db.users.createIndex({ "contacts": 1 })

// Chats collection
db.chats.createIndex({ participants: 1 })
db.chats.createIndex({ updated_at: -1 })  // recent chats list

// MessageStatus collection
db.messageStatus.createIndex({ message_id: 1, user_id: 1 }, { unique: true })
```

#### Message Pagination

Cursor-based pagination (NOT offset):
```
GET /messages?chat_id=xxx&before=<last_message_id>&limit=50
```

Never use `skip()` in MongoDB — it scans all skipped documents. Instead:
```python
query = {"chat_id": chat_id, "_id": {"$lt": ObjectId(before_id)}}
messages = await db.messages.find(query).sort("_id", -1).limit(50)
```

#### Caching Strategy

- **L1**: In-process LRU cache (user profiles, chat metadata) — 60s TTL
- **L2**: Redis (session tokens, presence, rate limits, recent message IDs)
- **L3**: MongoDB (source of truth)

#### Media Storage Strategy

```
Client ──► POST /api/v1/media/upload ──► Backend generates presigned S3 URL
Client ──► PUT {presigned_url} (direct to S3) ── bypasses backend
Backend stores S3 key in message.media_url
Client fetches via CDN (CloudFront in front of S3)
```

This removes media bandwidth from the API servers completely.