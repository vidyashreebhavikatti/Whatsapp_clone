/**
 * WebSocket Service
 * =================
 * Manages the WebSocket connection lifecycle:
 * - Connection with JWT auth
 * - Exponential backoff reconnection with jitter
 * - Event emitter pattern for decoupled event handling
 * - Heartbeat (ping every 15s) to keep presence alive
 * - Message queuing for messages sent while disconnected
 */

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';
const HEARTBEAT_INTERVAL = 15_000;   // 15s
const MAX_RECONNECT_DELAY = 30_000;  // 30s

class WebSocketService {
  constructor() {
    this.ws = null;
    this.userId = null;
    this.token = null;
    this.listeners = {};          // event → [callback, ...]
    this.reconnectAttempt = 0;
    this.reconnectTimer = null;
    this.heartbeatTimer = null;
    this.isIntentionallyClosed = false;
    this.pendingQueue = [];        // messages queued while disconnected
  }

  // ── Connection management ─────────────────────────────────────────────────

  connect(userId, token) {
    this.userId = userId;
    this.token = token;
    this.isIntentionallyClosed = false;
    this._createConnection();
  }

  disconnect() {
    this.isIntentionallyClosed = true;
    this._clearTimers();
    if (this.ws) {
      this.ws.close(1000, 'Intentional disconnect');
      this.ws = null;
    }
  }

  _createConnection() {
    const url = `${WS_URL}/ws/${this.userId}?token=${this.token}`;

    try {
      this.ws = new WebSocket(url);
    } catch (e) {
      console.error('[WS] Failed to create WebSocket:', e);
      this._scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      console.log('[WS] Connected');
      this.reconnectAttempt = 0;
      this._emit('_connected', {});
      this._startHeartbeat();
      this._flushQueue();   // send any queued messages
    };

    this.ws.onclose = (event) => {
      console.log(`[WS] Closed: code=${event.code} reason=${event.reason}`);
      this._clearTimers();
      this._emit('_disconnected', { code: event.code });

      if (!this.isIntentionallyClosed) {
        this._scheduleReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error('[WS] Error:', error);
      this._emit('_error', { error });
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        const { event: eventName, payload } = data;
        this._emit(eventName, payload);
      } catch (e) {
        console.error('[WS] Failed to parse message:', e, event.data);
      }
    };
  }

  _scheduleReconnect() {
    // Exponential backoff with jitter
    const base = Math.min(1000 * Math.pow(2, this.reconnectAttempt), MAX_RECONNECT_DELAY);
    const jitter = Math.random() * base * 0.3;
    const delay = base + jitter;

    this.reconnectAttempt++;
    console.log(`[WS] Reconnecting in ${Math.round(delay / 1000)}s (attempt ${this.reconnectAttempt})`);

    this._emit('_reconnecting', { attempt: this.reconnectAttempt, delay });

    this.reconnectTimer = setTimeout(() => {
      if (!this.isIntentionallyClosed) {
        this._createConnection();
      }
    }, delay);
  }

  _startHeartbeat() {
    this.heartbeatTimer = setInterval(() => {
      this.send('ping', {});
    }, HEARTBEAT_INTERVAL);
  }

  _clearTimers() {
    clearInterval(this.heartbeatTimer);
    clearTimeout(this.reconnectTimer);
    this.heartbeatTimer = null;
    this.reconnectTimer = null;
  }

  // ── Message sending ───────────────────────────────────────────────────────

  send(event, payload, eventId = null) {
    const message = {
      event,
      payload,
      event_id: eventId || crypto.randomUUID(),
    };

    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      // Queue message for when connection is restored
      if (event === 'send_message') {
        this.pendingQueue.push(message);
        console.log(`[WS] Queued message (disconnected): ${event}`);
      }
    }

    return message.event_id;
  }

  _flushQueue() {
    while (this.pendingQueue.length > 0 && this.ws?.readyState === WebSocket.OPEN) {
      const message = this.pendingQueue.shift();
      this.ws.send(JSON.stringify(message));
      console.log(`[WS] Flushed queued message: ${message.event}`);
    }
  }

  // ── Event system (observer pattern) ──────────────────────────────────────

  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);

    // Return unsubscribe function
    return () => this.off(event, callback);
  }

  off(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter((cb) => cb !== callback);
    }
  }

  _emit(event, payload) {
    (this.listeners[event] || []).forEach((cb) => {
      try {
        cb(payload);
      } catch (e) {
        console.error(`[WS] Listener error for event "${event}":`, e);
      }
    });
  }

  // ── Convenience event senders ─────────────────────────────────────────────

  joinChat(chatId) {
    this.send('join_chat', { chat_id: chatId });
  }

  leaveChat(chatId) {
    this.send('leave_chat', { chat_id: chatId });
  }

  sendMessage({ chatId, content, contentType = 'text', mediaUrl, replyToId }) {
    const tempId = crypto.randomUUID();
    const eventId = crypto.randomUUID();
    this.send('send_message', {
      chat_id: chatId,
      content,
      content_type: contentType,
      media_url: mediaUrl,
      reply_to_id: replyToId,
      temp_id: tempId,
    }, eventId);
    return { tempId, eventId };
  }

  markSeen(messageId, chatId) {
    this.send('message_seen', { message_id: messageId, chat_id: chatId });
  }

  startTyping(chatId) {
    this.send('typing', { chat_id: chatId });
  }

  stopTyping(chatId) {
    this.send('stop_typing', { chat_id: chatId });
  }

  get isConnected() {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}

// Singleton export
export const wsService = new WebSocketService();