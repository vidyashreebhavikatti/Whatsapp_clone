/**
 * ChatContext
 * ===========
 * Central state for all chat/message data.
 * Handles optimistic updates and WebSocket event integration.
 * 
 * Key design: messages are stored per-chat in a Map for O(1) lookup.
 */
import { createContext, useContext, useState, useCallback, useEffect, useRef } from 'react';
import { chatsAPI, messagesAPI } from '../services/api';
import { wsService } from '../services/websocket';
import { useAuth } from './AuthContext';

const ChatContext = createContext(null);

export function ChatProvider({ children }) {
  const { currentUser } = useAuth();

  // All chats list (sidebar)
  const [chats, setChats] = useState([]);
  // Currently open chat
  const [activeChat, setActiveChatState] = useState(null);
  // messages: Map<chatId, message[]>
  const [messagesMap, setMessagesMap] = useState(new Map());
  // typing indicators: Map<chatId, Set<userId>>
  const [typingMap, setTypingMap] = useState(new Map());
  // online presence: Set<userId>
  const [onlineUsers, setOnlineUsers] = useState(new Set());
  // WS connection status
  const [wsConnected, setWsConnected] = useState(false);

  const typingTimers = useRef({});   // chatId:userId → timeout ID

  // ── Load initial data ───────────────────────────────────────────────────

  const loadChats = useCallback(async () => {
    try {
      const { data } = await chatsAPI.listChats();
      setChats(data);
    } catch (e) {
      console.error('Failed to load chats:', e);
    }
  }, []);

  // ── Message operations ──────────────────────────────────────────────────

  const loadMessages = useCallback(async (chatId, before = null) => {
    const { data } = await messagesAPI.getMessages(chatId, before);
    setMessagesMap((prev) => {
      const existing = prev.get(chatId) || [];
      const merged = before
        ? [...data.messages, ...existing]   // prepend older messages
        : data.messages;
      return new Map(prev).set(chatId, merged);
    });
    return data;
  }, []);

  const addOptimisticMessage = useCallback((chatId, message) => {
    setMessagesMap((prev) => {
      const existing = prev.get(chatId) || [];
      return new Map(prev).set(chatId, [...existing, message]);
    });
  }, []);

  const updateMessageByTempId = useCallback((chatId, tempId, updates) => {
    setMessagesMap((prev) => {
      const msgs = prev.get(chatId) || [];
      return new Map(prev).set(
        chatId,
        msgs.map((m) => (m.temp_id === tempId || m.id === tempId ? { ...m, ...updates } : m))
      );
    });
  }, []);

  const updateMessageById = useCallback((chatId, messageId, updates) => {
    setMessagesMap((prev) => {
      const msgs = prev.get(chatId) || [];
      return new Map(prev).set(
        chatId,
        msgs.map((m) => (m.id === messageId ? { ...m, ...updates } : m))
      );
    });
  }, []);

  const markAllSeen = useCallback((chatId) => {
    setMessagesMap((prev) => {
      const msgs = prev.get(chatId) || [];
      return new Map(prev).set(
        chatId,
        msgs.map((m) =>
          m.sender_id !== currentUser?.id && m.status !== 'seen'
            ? { ...m, status: 'seen' }
            : m
        )
      );
    });
  }, [currentUser]);

  // ── Active chat ─────────────────────────────────────────────────────────

  const setActiveChat = useCallback(async (chat) => {
    // Leave previous chat room
    if (activeChat) {
      wsService.leaveChat(activeChat.id);
    }

    setActiveChatState(chat);

    if (!chat) return;

    // Join new chat room
    wsService.joinChat(chat.id);

    // Load messages if not already loaded
    if (!messagesMap.has(chat.id)) {
      await loadMessages(chat.id);
    }
  }, [activeChat, messagesMap, loadMessages]);

  // ── Send message ────────────────────────────────────────────────────────

  const sendMessage = useCallback(({ chatId, content, contentType = 'text', mediaUrl, replyToId }) => {
    if (!content.trim() && !mediaUrl) return;

    const tempId = crypto.randomUUID();
    const now = new Date().toISOString();

    // Optimistic update: show message immediately
    const optimisticMsg = {
      id: tempId,
      temp_id: tempId,
      chat_id: chatId,
      sender_id: currentUser?.id,
      content,
      content_type: contentType,
      media_url: mediaUrl,
      status: 'sending',
      created_at: now,
      updated_at: now,
      isOptimistic: true,
    };

    addOptimisticMessage(chatId, optimisticMsg);

    // Update chat list (last_message preview)
    setChats((prev) =>
      prev.map((c) =>
        c.id === chatId
          ? { ...c, last_message: { content, sender_id: currentUser?.id, created_at: now }, updated_at: now }
          : c
      ).sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
    );

    // Send via WebSocket
    wsService.sendMessage({ chatId, content, contentType, mediaUrl, replyToId });

    return tempId;
  }, [currentUser, addOptimisticMessage]);

  // ── Typing helpers ──────────────────────────────────────────────────────

  const _setTyping = useCallback((chatId, userId, isTyping) => {
    setTypingMap((prev) => {
      const chatTypers = new Set(prev.get(chatId) || []);
      if (isTyping) chatTypers.add(userId);
      else chatTypers.delete(userId);
      return new Map(prev).set(chatId, chatTypers);
    });
  }, []);

  // ── WebSocket event subscriptions ───────────────────────────────────────

  useEffect(() => {
    if (!currentUser) return;

    const unsubs = [];

    unsubs.push(wsService.on('_connected', () => setWsConnected(true)));
    unsubs.push(wsService.on('_disconnected', () => setWsConnected(false)));

    // New message received from another user
    unsubs.push(wsService.on('receive_message', (msg) => {
      const chatId = msg.chat_id;
      setMessagesMap((prev) => {
        const existing = prev.get(chatId) || [];
        // Avoid duplicates
        if (existing.some((m) => m.id === msg.id)) return prev;
        return new Map(prev).set(chatId, [...existing, { ...msg, id: msg.id }]);
      });

      // Update chat list preview
      setChats((prev) =>
        prev.map((c) =>
          c.id === chatId
            ? { ...c, last_message: msg, updated_at: msg.created_at }
            : c
        ).sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))
      );
    }));

    // Our message was acknowledged (temp_id → real_id)
    unsubs.push(wsService.on('message_ack', (ack) => {
      updateMessageByTempId(ack.chat_id, ack.temp_id, {
        id: ack.real_id,
        temp_id: ack.temp_id,
        status: ack.status,
        isOptimistic: false,
      });
    }));

    // Our message was seen (update ticks)
    unsubs.push(wsService.on('message_seen', ({ message_id, chat_id, seen_by }) => {
      // Find which chat this message belongs to
      setMessagesMap((prev) => {
        // Update across all chats (message_id is unique)
        const updated = new Map(prev);
        for (const [cid, msgs] of updated.entries()) {
          const idx = msgs.findIndex((m) => m.id === message_id);
          if (idx !== -1) {
            const newMsgs = [...msgs];
            newMsgs[idx] = { ...newMsgs[idx], status: 'seen' };
            updated.set(cid, newMsgs);
            break;
          }
        }
        return updated;
      });
    }));

    // Batch seen (when user opens a chat with many unread)
    unsubs.push(wsService.on('messages_seen_batch', ({ chat_id }) => {
      setMessagesMap((prev) => {
        const msgs = prev.get(chat_id) || [];
        return new Map(prev).set(
          chat_id,
          msgs.map((m) => m.sender_id === currentUser.id && m.status !== 'seen' ? { ...m, status: 'seen' } : m)
        );
      });
    }));

    // Typing indicator
    unsubs.push(wsService.on('typing', ({ chat_id, user_id }) => {
      if (user_id === currentUser.id) return;
      _setTyping(chat_id, user_id, true);

      // Auto-clear typing after 4s (in case stop_typing missed)
      const key = `${chat_id}:${user_id}`;
      clearTimeout(typingTimers.current[key]);
      typingTimers.current[key] = setTimeout(() => {
        _setTyping(chat_id, user_id, false);
      }, 4000);
    }));

    unsubs.push(wsService.on('stop_typing', ({ chat_id, user_id }) => {
      _setTyping(chat_id, user_id, false);
    }));

    // Presence events
    unsubs.push(wsService.on('user_online', ({ user_id }) => {
      setOnlineUsers((prev) => new Set([...prev, user_id]));
    }));

    unsubs.push(wsService.on('user_offline', ({ user_id }) => {
      setOnlineUsers((prev) => {
        const next = new Set(prev);
        next.delete(user_id);
        return next;
      });
    }));

    return () => unsubs.forEach((fn) => fn());
  }, [currentUser, updateMessageByTempId, updateMessageById, _setTyping]);

  return (
    <ChatContext.Provider value={{
      chats, setChats, loadChats,
      activeChat, setActiveChat,
      messagesMap, loadMessages, sendMessage,
      typingMap,
      onlineUsers,
      wsConnected,
      markAllSeen,
    }}>
      {children}
    </ChatContext.Provider>
  );
}

export const useChat = () => {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChat must be used within ChatProvider');
  return ctx;
};