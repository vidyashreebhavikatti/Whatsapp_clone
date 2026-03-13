# WhatsApp Web Clone — Production-Grade Real-Time Messaging

> A full-stack WhatsApp Web clone built with FastAPI, React, MongoDB, Redis, and WebSockets.  
> Designed for scale: supports millions of concurrent users via horizontal scaling and Redis Pub/Sub.

---

## Table of Contents

1. [Architecture Overview](#architecture)
2. [Tech Stack](#tech-stack)
3. [Quick Start (Docker)](#quick-start-docker)
4. [Quick Start (Local)](#quick-start-local)
5. [Database Design](#database-design)
6. [API Reference](#api-reference)
7. [WebSocket Protocol](#websocket-protocol)
8. [Scaling Strategy](#scaling-strategy)
9. [Git Strategy](#git-strategy)
10. [Interview Guide](#interview-guide)

---

## Architecture

```
Client → Nginx (SSL/LB) → FastAPI Instances → MongoDB Replica Set
                                         ↕
                                    Redis Cluster
                                (Pub/Sub + Presence + Cache)
                                         ↕
                                  S3 Object Storage
                              (Media files via presigned URLs)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12, FastAPI 0.104 |
| **Real-time** | Native WebSockets (ASGI) |
| **Database** | MongoDB 7 (Motor async driver) |
| **Cache/PubSub** | Redis 7 |
| **Auth** | JWT (python-jose), bcrypt (passlib) |
| **Media** | S3/MinIO (presigned URL uploads) |
| **Frontend** | React 18, Context API, native WebSocket |
| **Server** | Uvicorn (ASGI), Gunicorn (production) |
| **Proxy** | Nginx |
| **Containers** | Docker, Docker Compose |

---

## Quick Start (Docker)

```bash
# Clone repository
git clone https://github.com/yourname/whatsapp-clone.git
cd whatsapp-clone

# Copy and configure environment
cp backend/.env.example backend/.env

# Start all services
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f backend
```

Services will be available at:
- **App**: http://localhost (Nginx)
- **API**: http://localhost/api/v1
- **API Docs**: http://localhost:8000/docs (dev mode)
- **MinIO Console**: http://localhost:9001 (minioadmin/minioadmin)

---

## Quick Start (Local Development)

### Prerequisites
- Python 3.12+
- Node.js 20+
- MongoDB 7 running locally
- Redis 7 running locally

### Backend

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your local settings

# Start server
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev
# → http://localhost:5173
```

---

## Database Design

### Collections

#### `users`
```json
{
  "_id": ObjectId("..."),
  "phone": "+14155552671",
  "username": "Alice",
  "password_hash": "$2b$12$...",
  "status": "Hey there!",
  "avatar_url": "https://s3.../avatar.jpg",
  "is_online": false,
  "last_seen": ISODate("2024-01-15T10:30:00Z"),
  "created_at": ISODate("2024-01-01T00:00:00Z"),
  "updated_at": ISODate("2024-01-15T10:30:00Z")
}
```

**Indexes**: `phone` (unique), `username` (text search)

---

#### `chats`
```json
{
  "_id": ObjectId("..."),
  "type": "direct",
  "participants": [ObjectId("user1"), ObjectId("user2")],
  "group_id": null,
  "last_message": {
    "id": "...",
    "content": "Hello!",
    "sender_id": "...",
    "created_at": ISODate("...")
  },
  "created_at": ISODate("..."),
  "updated_at": ISODate("...")
}
```

**Indexes**: `participants` (for lookup), `updated_at desc` (for sidebar sort)

---

#### `messages`
```json
{
  "_id": ObjectId("..."),
  "chat_id": ObjectId("..."),
  "sender_id": ObjectId("..."),
  "content": "Hello, World!",
  "content_type": "text",
  "media_url": null,
  "thumbnail_url": null,
  "reply_to": null,
  "status": "seen",
  "is_deleted": false,
  "created_at": ISODate("..."),
  "updated_at": ISODate("...")
}
```

**Indexes**: `(chat_id, _id desc)` for cursor pagination, `(chat_id, status)` for unread counts

---

#### `groups`
```json
{
  "_id": ObjectId("..."),
  "name": "Team Chat",
  "description": "Engineering team",
  "avatar_url": null,
  "created_by": ObjectId("..."),
  "members": [
    { "user_id": ObjectId("..."), "role": "admin", "joined_at": ISODate("...") },
    { "user_id": ObjectId("..."), "role": "member", "joined_at": ISODate("...") }
  ],
  "created_at": ISODate("...")
}
```

---

## API Reference

### Authentication
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/auth/register` | Register new user |
| POST | `/api/v1/auth/login` | Login, get tokens |
| POST | `/api/v1/auth/refresh` | Refresh access token |
| POST | `/api/v1/auth/logout` | Logout |

### Users
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/users/me` | Get own profile |
| PATCH | `/api/v1/users/me` | Update profile |
| GET | `/api/v1/users/search?q=alice` | Search users |
| GET | `/api/v1/users/{id}` | Get user profile |

### Chats
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/chats/` | List all chats |
| POST | `/api/v1/chats/direct` | Create/get 1-1 chat |
| POST | `/api/v1/chats/group` | Create group chat |
| GET | `/api/v1/chats/{id}` | Get chat details |

### Messages
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/messages/{chat_id}` | Get messages (paginated) |
| DELETE | `/api/v1/messages/{chat_id}/{id}` | Delete message (soft) |

---

## WebSocket Protocol

**Connect**: `wss://domain.com/ws/{user_id}?token=<JWT>`

### Client → Server Events

```json
// Join chat room
{ "event": "join_chat", "payload": { "chat_id": "..." }, "event_id": "uuid" }

// Send message
{ "event": "send_message", "payload": { "chat_id": "...", "content": "Hello!", "content_type": "text", "temp_id": "uuid" }, "event_id": "uuid" }

// Mark message seen
{ "event": "message_seen", "payload": { "message_id": "...", "chat_id": "..." }, "event_id": "uuid" }

// Typing indicators
{ "event": "typing", "payload": { "chat_id": "..." }, "event_id": "uuid" }
{ "event": "stop_typing", "payload": { "chat_id": "..." }, "event_id": "uuid" }

// Heartbeat
{ "event": "ping", "payload": {}, "event_id": "uuid" }
```

### Server → Client Events

```json
// Message acknowledgement (replaces optimistic bubble)
{ "event": "message_ack", "payload": { "temp_id": "uuid", "real_id": "...", "status": "sent", "created_at": "..." } }

// Incoming message
{ "event": "receive_message", "payload": { "id": "...", "chat_id": "...", "sender_id": "...", "content": "...", "status": "delivered", "created_at": "..." } }

// Message seen by recipient
{ "event": "message_seen", "payload": { "message_id": "...", "chat_id": "...", "seen_by": "...", "timestamp": "..." } }

// Presence
{ "event": "user_online", "payload": { "user_id": "..." } }
{ "event": "user_offline", "payload": { "user_id": "..." } }

// Typing
{ "event": "typing", "payload": { "chat_id": "...", "user_id": "..." } }
{ "event": "stop_typing", "payload": { "chat_id": "...", "user_id": "..." } }
```

---

## Scaling Strategy

### Horizontal Scaling
```
                    Load Balancer (Nginx / AWS ALB)
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      FastAPI #1       FastAPI #2       FastAPI #3
          │                │                │
          └────────────────┼────────────────┘
                           │
                      Redis Cluster
                    (Pub/Sub bridge)
```

WebSocket state is fully externalized to Redis, so any instance can handle any client.

### Database Scaling
- MongoDB Replica Set: 1 primary + 2 secondaries
- Read from secondaries for message history (eventual consistency acceptable)
- Shard by `chat_id` when collection exceeds 100M documents

### Caching Layers
- **Redis L1**: Online presence, JWT sessions, rate limit counters
- **Redis L2**: Recent message IDs (deduplication), typing state
- **Application L1**: In-memory LRU for user profiles (60s TTL)

---

## Git Strategy

### Branch Model
```
main          (production, protected)
  └── develop (integration branch)
        ├── feature/auth
        ├── feature/websocket
        ├── feature/chat-ui
        └── feature/media-upload
```

### 14-Day Development Roadmap

| Day | Activity | Commits |
|-----|----------|---------|
| **Day 1** | Project setup, folder structure, Docker config | 3 commits |
| **Day 2** | MongoDB schema design, Motor setup, index creation | 4 commits |
| **Day 3** | Auth endpoints (register/login/refresh) + JWT | 5 commits |
| **Day 4** | *No commits — architecture review & research day* | — |
| **Day 5** | Users + Chats REST endpoints | 6 commits |
| **Day 6** | Messages endpoint + cursor-based pagination | 4 commits |
| **Day 7** | WebSocket connection manager + Redis Pub/Sub | 7 commits |
| **Day 8** | WebSocket event handlers (send, seen, typing) | 6 commits |
| **Day 9** | *No commits — debugging presence sync issues* | — |
| **Day 10** | Frontend scaffold + AuthContext + API service | 5 commits |
| **Day 11** | ChatContext + WebSocket service + reconnect logic | 6 commits |
| **Day 12** | MessageBubble + ticks + TypingIndicator + infinite scroll | 8 commits |
| **Day 13** | *No commits — performance profiling + optimization* | — |
| **Day 14** | Docker Compose + Nginx config + README | 4 commits |

### Example Commit Messages
```
feat(auth): implement JWT register/login endpoints with bcrypt hashing
feat(ws): add ConnectionManager with Redis Pub/Sub cross-instance routing
fix(ws): resolve race condition in room membership tracking
perf(messages): switch to cursor-based pagination, remove skip()
feat(ui): implement optimistic message updates with temp_id swap
fix(presence): handle edge case where TTL expires before disconnect event
docs: add WebSocket protocol specification to README
chore(docker): configure MongoDB replica set init container
```

### PR Description Template
```markdown
## Summary
[What this PR does in 1-2 sentences]

## Changes
- List of key changes

## Testing
- [ ] Unit tests pass
- [ ] Manual end-to-end test: [describe scenario]
- [ ] No regression in existing functionality

## Screenshots (if UI change)
[Before / After]

## Related Issues
Closes #42
```

---

## Interview Guide

### Elevator Pitch (30 seconds)
> "I built a production-grade WhatsApp Web clone that supports real-time messaging via WebSockets. The backend is FastAPI with an async MongoDB driver. I used Redis Pub/Sub to make WebSockets work across multiple server instances — so any server can route messages to any client. The frontend uses optimistic UI updates for instant perceived performance, with exponential backoff reconnect logic. The whole thing runs in Docker with a MongoDB replica set and MinIO for media."

### How to Answer "How Does Real-Time Work?"
1. Client connects via WebSocket (WSS upgrade from HTTP)
2. Server registers connection in ConnectionManager dictionary
3. Client sends `send_message` event
4. Server persists to MongoDB, then publishes to Redis channel `chat:{id}`
5. ALL instances subscribe to Redis — the one with the recipient's connection delivers it
6. Recipient's client receives `receive_message`, sends `message_seen`
7. Server publishes seen event → sender's client updates to blue ticks

### How to Answer "How Would You Scale to 10M Users?"
1. **WebSocket tier**: 10M × avg 1 connection × 50KB RAM = ~500GB RAM across ~200 servers (16GB RAM each)
2. **MongoDB sharding**: Shard `messages` collection by `chat_id` hash → distribute load
3. **Redis Cluster**: 6-node cluster with hash slots for Pub/Sub distribution
4. **CDN**: CloudFront in front of S3 for media (zero API server media bandwidth)
5. **Read replicas**: Chat history from MongoDB secondaries (eventual consistency OK)
6. **Message queue**: For high-volume groups, use Kafka between WebSocket and persistence layers
7. **Microservices split**: Separate presence service, notification service, media service

### Key Technical Decisions
| Decision | Why |
|----------|-----|
| MongoDB over PostgreSQL | Flexible schema, native document storage for messages |
| Redis Pub/Sub over Kafka | Lower latency for real-time events (sub-millisecond) |
| Cursor pagination over offset | O(log n) vs O(n) — essential for large message collections |
| Optimistic UI | Eliminates ~200ms perceived latency for message sends |
| Presigned S3 URLs | Removes media traffic from API servers completely |
| Soft delete for messages | Maintains conversation context, enables "This message was deleted" |

### Trade-offs
- **Redis Pub/Sub vs Kafka**: Pub/Sub has no persistence (messages lost if subscriber dies). Kafka is durably logged. For a messaging app, brief delivery gaps during crashes are acceptable; we handle this with sync_request on reconnect.
- **MongoDB vs PostgreSQL**: NoSQL gives schema flexibility but lacks ACID transactions across documents. Message-level consistency is sufficient for chat; no complex multi-entity transactions needed.
- **JWT statelessness**: Can't invalidate tokens instantly without a Redis blacklist. Trade-off: simplicity vs instant logout.

---

## Production Deployment (AWS)

```bash
# 1. Launch EC2 instances (t3.large for backend, c5.xlarge for high load)
# 2. Install Docker
curl -fsSL https://get.docker.com | sh

# 3. Clone repo
git clone your-repo && cd whatsapp-clone

# 4. Configure production .env
cp backend/.env.example backend/.env
# Set: SECRET_KEY, MONGODB_URL (Atlas), REDIS_URL (ElastiCache), 
#      AWS credentials, allowed origins

# 5. Start services
docker compose -f docker-compose.prod.yml up -d

# 6. SSL with Certbot
sudo certbot --nginx -d yourdomain.com

# 7. Setup process monitoring
pm2 start ecosystem.config.js  # or systemd
```

### Recommended AWS Architecture
- **EC2 Auto Scaling Group**: 2-10 t3.large instances behind ALB
- **MongoDB Atlas**: M30+ cluster with 3 nodes
- **ElastiCache Redis**: r6g.large cluster mode
- **S3 + CloudFront**: Media storage and CDN
- **ALB**: Sticky sessions (optional) or stateless via Redis