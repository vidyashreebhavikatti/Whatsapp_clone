import { useRef, useCallback } from 'react';
import { wsService } from '../services/websocket';

/**
 * useTyping
 * =========
 * Sends typing / stop_typing events with debouncing.
 * - Sends "typing" immediately on first keystroke
 * - Sends "stop_typing" after 2s of no keystrokes
 * - Never sends duplicate "typing" events
 */
export function useTyping(chatId) {
  const isTypingRef = useRef(false);
  const stopTimerRef = useRef(null);

  const onKeyPress = useCallback(() => {
    if (!chatId) return;

    if (!isTypingRef.current) {
      isTypingRef.current = true;
      wsService.startTyping(chatId);
    }

    // Reset stop timer on every keystroke
    clearTimeout(stopTimerRef.current);
    stopTimerRef.current = setTimeout(() => {
      isTypingRef.current = false;
      wsService.stopTyping(chatId);
    }, 2000);
  }, [chatId]);

  const onBlur = useCallback(() => {
    if (!chatId || !isTypingRef.current) return;
    clearTimeout(stopTimerRef.current);
    isTypingRef.current = false;
    wsService.stopTyping(chatId);
  }, [chatId]);

  return { onKeyPress, onBlur };
}