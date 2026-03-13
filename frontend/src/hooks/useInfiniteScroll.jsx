import { useRef, useCallback, useState } from 'react';

/**
 * useInfiniteScroll
 * =================
 * Detects when user scrolls to top of message list
 * and triggers loading of older messages.
 */
export function useInfiniteScroll(onLoadMore, hasMore) {
  const containerRef = useRef(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleScroll = useCallback(async () => {
    const container = containerRef.current;
    if (!container || isLoading || !hasMore) return;

    // Trigger when within 100px of top
    if (container.scrollTop < 100) {
      const prevScrollHeight = container.scrollHeight;
      setIsLoading(true);

      try {
        await onLoadMore();
      } finally {
        setIsLoading(false);

        // Preserve scroll position after prepending older messages
        requestAnimationFrame(() => {
          if (container) {
            container.scrollTop = container.scrollHeight - prevScrollHeight;
          }
        });
      }
    }
  }, [isLoading, hasMore, onLoadMore]);

  const scrollToBottom = useCallback((smooth = false) => {
    const container = containerRef.current;
    if (container) {
      container.scrollTo({
        top: container.scrollHeight,
        behavior: smooth ? 'smooth' : 'instant',
      });
    }
  }, []);

  return { containerRef, handleScroll, isLoading, scrollToBottom };
}