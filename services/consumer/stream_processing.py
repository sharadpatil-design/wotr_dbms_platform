"""
Stream processing enhancements: windowing, aggregations, and real-time analytics
"""
import os
import json
import time
from typing import Dict, List, Any, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


class TimeWindow:
    """Time-based window for stream processing"""
    
    def __init__(self, duration_seconds: int, slide_seconds: Optional[int] = None):
        """
        Initialize time window
        
        Args:
            duration_seconds: Window duration in seconds
            slide_seconds: Slide interval (None for tumbling window)
        """
        self.duration = duration_seconds
        self.slide = slide_seconds or duration_seconds  # Tumbling by default
        self.events = deque()
    
    def add_event(self, event: Dict[str, Any], timestamp: float):
        """Add event to window"""
        self.events.append((timestamp, event))
        self._evict_old_events(timestamp)
    
    def _evict_old_events(self, current_time: float):
        """Remove events outside the window"""
        cutoff_time = current_time - self.duration
        while self.events and self.events[0][0] < cutoff_time:
            self.events.popleft()
    
    def get_events(self) -> List[Dict[str, Any]]:
        """Get all events in current window"""
        return [event for _, event in self.events]
    
    def count(self) -> int:
        """Count events in window"""
        return len(self.events)
    
    def is_ready(self, current_time: float, last_trigger: float) -> bool:
        """Check if window is ready to trigger"""
        return (current_time - last_trigger) >= self.slide


class SessionWindow:
    """Session-based window (groups events by session with timeout)"""
    
    def __init__(self, session_timeout_seconds: int = 300):
        """
        Initialize session window
        
        Args:
            session_timeout_seconds: Session timeout in seconds (default 5 minutes)
        """
        self.timeout = session_timeout_seconds
        self.sessions: Dict[str, Dict[str, Any]] = {}
    
    def add_event(self, event: Dict[str, Any], session_id: str, timestamp: float):
        """Add event to session"""
        if session_id not in self.sessions:
            self.sessions[session_id] = {
                "events": [],
                "start_time": timestamp,
                "last_activity": timestamp
            }
        
        self.sessions[session_id]["events"].append(event)
        self.sessions[session_id]["last_activity"] = timestamp
        
        # Clean up expired sessions
        self._cleanup_expired_sessions(timestamp)
    
    def _cleanup_expired_sessions(self, current_time: float):
        """Remove expired sessions"""
        expired = [
            sid for sid, session in self.sessions.items()
            if (current_time - session["last_activity"]) > self.timeout
        ]
        
        for sid in expired:
            logger.info(f"Session {sid} expired, {len(self.sessions[sid]['events'])} events")
            del self.sessions[sid]
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data"""
        return self.sessions.get(session_id)
    
    def get_active_sessions(self) -> List[str]:
        """Get list of active session IDs"""
        return list(self.sessions.keys())


class StreamAggregator:
    """Aggregate stream data in real-time"""
    
    def __init__(self):
        self.counters: Dict[str, int] = defaultdict(int)
        self.sums: Dict[str, float] = defaultdict(float)
        self.groups: Dict[str, Dict[str, Any]] = defaultdict(lambda: defaultdict(int))
    
    def count(self, key: str):
        """Increment counter"""
        self.counters[key] += 1
    
    def sum(self, key: str, value: float):
        """Add to sum"""
        self.sums[key] += value
    
    def group_count(self, group_key: str, value_key: str):
        """Count by group"""
        self.groups[group_key][value_key] += 1
    
    def get_count(self, key: str) -> int:
        """Get counter value"""
        return self.counters.get(key, 0)
    
    def get_sum(self, key: str) -> float:
        """Get sum value"""
        return self.sums.get(key, 0.0)
    
    def get_group_counts(self, group_key: str) -> Dict[str, int]:
        """Get counts by group"""
        return dict(self.groups.get(group_key, {}))
    
    def top_k(self, group_key: str, k: int = 10) -> List[tuple]:
        """Get top K items in group"""
        group = self.groups.get(group_key, {})
        return sorted(group.items(), key=lambda x: x[1], reverse=True)[:k]
    
    def reset(self):
        """Reset all aggregations"""
        self.counters.clear()
        self.sums.clear()
        self.groups.clear()


class StreamProcessor:
    """Main stream processor with windowing and aggregations"""
    
    def __init__(self, window_duration: int = 60):
        """
        Initialize stream processor
        
        Args:
            window_duration: Time window duration in seconds
        """
        self.time_window = TimeWindow(window_duration)
        self.session_window = SessionWindow(session_timeout_seconds=300)
        self.aggregator = StreamAggregator()
        self.last_trigger_time = time.time()
    
    def process_event(self, event: Dict[str, Any]):
        """
        Process incoming event
        
        Args:
            event: Event data
        """
        current_time = time.time()
        
        # Extract event details
        event_type = event.get("payload", {}).get("event_type", "unknown")
        source = event.get("payload", {}).get("source", "unknown")
        session_id = event.get("payload", {}).get("session_id")
        
        # Add to time window
        self.time_window.add_event(event, current_time)
        
        # Add to session window if session_id present
        if session_id:
            self.session_window.add_event(event, session_id, current_time)
        
        # Update aggregations
        self.aggregator.count(f"event_type:{event_type}")
        self.aggregator.count(f"source:{source}")
        self.aggregator.group_count("by_event_type", event_type)
        self.aggregator.group_count("by_source", source)
        
        # Check if window should trigger
        if self.time_window.is_ready(current_time, self.last_trigger_time):
            self._trigger_window(current_time)
    
    def _trigger_window(self, current_time: float):
        """Trigger window computation"""
        events_in_window = self.time_window.get_events()
        
        logger.info(
            "Window triggered",
            extra={
                "window_size": len(events_in_window),
                "duration": self.time_window.duration,
                "timestamp": current_time
            }
        )
        
        # Perform window aggregations
        event_types = self.aggregator.get_group_counts("by_event_type")
        sources = self.aggregator.get_group_counts("by_source")
        
        logger.info(
            "Window aggregations",
            extra={
                "event_types": event_types,
                "sources": sources,
                "top_sources": self.aggregator.top_k("by_source", 5)
            }
        )
        
        self.last_trigger_time = current_time
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current processing statistics"""
        return {
            "window_count": self.time_window.count(),
            "active_sessions": len(self.session_window.get_active_sessions()),
            "event_type_counts": self.aggregator.get_group_counts("by_event_type"),
            "source_counts": self.aggregator.get_group_counts("by_source"),
            "top_sources": self.aggregator.top_k("by_source", 5)
        }


class StreamJoiner:
    """Join multiple streams based on keys"""
    
    def __init__(self, join_window_seconds: int = 60):
        """
        Initialize stream joiner
        
        Args:
            join_window_seconds: Window for join operations
        """
        self.join_window = join_window_seconds
        self.left_stream: Dict[str, tuple] = {}  # key -> (timestamp, event)
        self.right_stream: Dict[str, tuple] = {}
        self.joined_events: List[Dict[str, Any]] = []
    
    def add_left(self, key: str, event: Dict[str, Any], timestamp: float):
        """Add event to left stream"""
        self.left_stream[key] = (timestamp, event)
        self._cleanup_old_events(timestamp)
        self._try_join(key, timestamp)
    
    def add_right(self, key: str, event: Dict[str, Any], timestamp: float):
        """Add event to right stream"""
        self.right_stream[key] = (timestamp, event)
        self._cleanup_old_events(timestamp)
        self._try_join(key, timestamp)
    
    def _try_join(self, key: str, current_time: float):
        """Attempt to join events on key"""
        if key in self.left_stream and key in self.right_stream:
            left_time, left_event = self.left_stream[key]
            right_time, right_event = self.right_stream[key]
            
            # Check if within join window
            time_diff = abs(left_time - right_time)
            if time_diff <= self.join_window:
                joined = {
                    "key": key,
                    "left": left_event,
                    "right": right_event,
                    "time_diff": time_diff,
                    "joined_at": current_time
                }
                self.joined_events.append(joined)
                
                logger.info(f"Successfully joined events on key: {key}")
                
                # Remove from streams after join
                del self.left_stream[key]
                del self.right_stream[key]
    
    def _cleanup_old_events(self, current_time: float):
        """Remove events outside join window"""
        cutoff = current_time - self.join_window
        
        self.left_stream = {
            k: v for k, v in self.left_stream.items()
            if v[0] >= cutoff
        }
        
        self.right_stream = {
            k: v for k, v in self.right_stream.items()
            if v[0] >= cutoff
        }
    
    def get_joined_events(self) -> List[Dict[str, Any]]:
        """Get all joined events"""
        return self.joined_events
    
    def get_unjoined_count(self) -> tuple:
        """Get count of unjoined events"""
        return len(self.left_stream), len(self.right_stream)
