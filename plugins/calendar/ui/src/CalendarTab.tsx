/**
 * CalendarTab - Main calendar component with month and Gantt views
 *
 * Features:
 * - Month view: Traditional calendar grid
 * - Gantt view: Weekly timeline view
 * - Multiple calendar support with color coding
 * - Real-time updates from calendar domain events
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { MonthView } from './MonthView';
import { WeekGantt } from './WeekGantt';
import { Calendar, CalendarEvent, ViewMode } from './types';
import './CalendarTab.css';

// Re-export types
export type { PluginContext, DomainEventData } from './types';

interface CalendarTabProps {
  sendMessage?: (message: string) => void;
  sessionId?: string;
  subscribeToDomainEvents?: (
    domainId: string,
    callback: (event: { eventType: string; data: Record<string, unknown> }) => void
  ) => () => void;
  requestDomainState?: (domainId: string) => Promise<boolean>;
  isLLMResponding?: boolean;
}

export function CalendarTab({
  sendMessage,
  sessionId,
  subscribeToDomainEvents,
  requestDomainState,
  isLLMResponding = false,
}: CalendarTabProps) {
  const [calendars, setCalendars] = useState<Map<string, Calendar>>(new Map());
  const [viewMode, setViewMode] = useState<ViewMode>('month');
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [visibleCalendarIds, setVisibleCalendarIds] = useState<Set<string>>(new Set());

  // Subscribe to domain events
  useEffect(() => {
    if (!subscribeToDomainEvents || !sessionId) return;

    console.log('[CalendarTab] Subscribing to domain events for session:', sessionId);

    const unsubscribe = subscribeToDomainEvents('calendar', (event) => {
      console.log('[CalendarTab] Received domain event:', event);
      const data = event.data;

      switch (event.eventType) {
        case 'calendar_created': {
          const calendar = data.calendar as Calendar;
          console.log('[CalendarTab] Calendar created:', calendar.id);
          setCalendars(prev => {
            const next = new Map(prev);
            next.set(calendar.id, calendar);
            return next;
          });
          setVisibleCalendarIds(prev => {
            const next = new Set(prev);
            next.add(calendar.id);
            return next;
          });
          break;
        }

        case 'calendar_deleted': {
          const calendarId = data.calendarId as string || data.calendar_id as string;
          console.log('[CalendarTab] Calendar deleted:', calendarId);
          setCalendars(prev => {
            const next = new Map(prev);
            next.delete(calendarId);
            return next;
          });
          setVisibleCalendarIds(prev => {
            const next = new Set(prev);
            next.delete(calendarId);
            return next;
          });
          break;
        }

        case 'event_created': {
          const calendarId = data.calendarId as string || data.calendar_id as string;
          const eventData = data.event as CalendarEvent;
          console.log('[CalendarTab] Event created:', eventData.id);
          setCalendars(prev => {
            const calendar = prev.get(calendarId);
            if (!calendar) return prev;
            const next = new Map(prev);
            next.set(calendarId, {
              ...calendar,
              events: [...calendar.events, eventData],
            });
            return next;
          });
          break;
        }

        case 'event_updated': {
          const calendarId = data.calendarId as string || data.calendar_id as string;
          const eventData = data.event as CalendarEvent;
          console.log('[CalendarTab] Event updated:', eventData.id);
          setCalendars(prev => {
            const calendar = prev.get(calendarId);
            if (!calendar) return prev;
            const next = new Map(prev);
            next.set(calendarId, {
              ...calendar,
              events: calendar.events.map(e => e.id === eventData.id ? eventData : e),
            });
            return next;
          });
          break;
        }

        case 'event_deleted': {
          const calendarId = data.calendarId as string || data.calendar_id as string;
          const eventId = data.eventId as string || data.event_id as string;
          console.log('[CalendarTab] Event deleted:', eventId);
          setCalendars(prev => {
            const calendar = prev.get(calendarId);
            if (!calendar) return prev;
            const next = new Map(prev);
            next.set(calendarId, {
              ...calendar,
              events: calendar.events.filter(e => e.id !== eventId),
            });
            return next;
          });
          if (selectedEventId === eventId) {
            setSelectedEventId(null);
          }
          break;
        }

        case 'sync_status': {
          const calendarId = data.calendarId as string || data.calendar_id as string;
          const status = data.status as string;
          console.log('[CalendarTab] Sync status:', calendarId, status);
          setCalendars(prev => {
            const calendar = prev.get(calendarId);
            if (!calendar) return prev;
            const next = new Map(prev);
            next.set(calendarId, {
              ...calendar,
              syncStatus: {
                state: status as 'idle' | 'syncing' | 'synced' | 'error',
                lastSynced: data.lastSynced as string | undefined || data.last_synced as string | undefined,
                error: data.error as string | undefined,
              },
            });
            return next;
          });
          break;
        }

        case 'calendar_state_sync':
        case 'calendar_state_sync': {
          const calendarList = data.calendars as Calendar[] | undefined;
          console.log('[CalendarTab] State sync:', calendarList?.length, 'calendars');
          if (calendarList) {
            setCalendars(new Map(calendarList.map(c => [c.id, c])));
            // Make all calendars visible by default
            setVisibleCalendarIds(new Set(calendarList.map(c => c.id)));
          }
          break;
        }
      }
    });

    return unsubscribe;
  }, [subscribeToDomainEvents, sessionId, selectedEventId]);

  // Request current state on mount
  useEffect(() => {
    if (!requestDomainState || !sessionId) return;

    console.log('[CalendarTab] Requesting calendar state for session:', sessionId);
    requestDomainState('calendar').then((hasState) => {
      console.log('[CalendarTab] State request result:', hasState);
    }).catch((err) => {
      console.warn('[CalendarTab] Failed to request domain state:', err);
    });
  }, [requestDomainState, sessionId]);

  // Get all visible events across calendars
  const visibleEvents = useMemo(() => {
    const events: Array<CalendarEvent & { calendarId: string; calendarColor: string }> = [];
    for (const calendar of calendars.values()) {
      if (visibleCalendarIds.has(calendar.id)) {
        for (const event of calendar.events) {
          events.push({
            ...event,
            calendarId: calendar.id,
            calendarColor: event.color || calendar.color,
          });
        }
      }
    }
    return events;
  }, [calendars, visibleCalendarIds]);

  // Navigation handlers
  const handlePrevious = useCallback(() => {
    setCurrentDate(prev => {
      const next = new Date(prev);
      if (viewMode === 'month') {
        next.setMonth(next.getMonth() - 1);
      } else {
        next.setDate(next.getDate() - 7);
      }
      return next;
    });
  }, [viewMode]);

  const handleNext = useCallback(() => {
    setCurrentDate(prev => {
      const next = new Date(prev);
      if (viewMode === 'month') {
        next.setMonth(next.getMonth() + 1);
      } else {
        next.setDate(next.getDate() + 7);
      }
      return next;
    });
  }, [viewMode]);

  const handleToday = useCallback(() => {
    setCurrentDate(new Date());
  }, []);

  // Toggle calendar visibility
  const toggleCalendarVisibility = useCallback((calendarId: string) => {
    setVisibleCalendarIds(prev => {
      const next = new Set(prev);
      if (next.has(calendarId)) {
        next.delete(calendarId);
      } else {
        next.add(calendarId);
      }
      return next;
    });
  }, []);

  // Handle manual sync request
  const handleSync = useCallback(() => {
    if (requestDomainState && sessionId) {
      requestDomainState('calendar').catch(console.error);
    }
  }, [requestDomainState, sessionId]);

  // Handle event click
  const handleEventClick = useCallback((eventId: string) => {
    setSelectedEventId(eventId === selectedEventId ? null : eventId);
  }, [selectedEventId]);

  const calendarList = useMemo(() => Array.from(calendars.values()), [calendars]);

  // Format current date for header
  const headerTitle = useMemo(() => {
    if (viewMode === 'month') {
      return currentDate.toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
    } else {
      // Week view - show week range
      const weekStart = new Date(currentDate);
      weekStart.setDate(weekStart.getDate() - weekStart.getDay());
      const weekEnd = new Date(weekStart);
      weekEnd.setDate(weekEnd.getDate() + 6);

      const startMonth = weekStart.toLocaleDateString('en-US', { month: 'short' });
      const endMonth = weekEnd.toLocaleDateString('en-US', { month: 'short' });

      if (startMonth === endMonth) {
        return `${startMonth} ${weekStart.getDate()} - ${weekEnd.getDate()}, ${weekEnd.getFullYear()}`;
      }
      return `${startMonth} ${weekStart.getDate()} - ${endMonth} ${weekEnd.getDate()}, ${weekEnd.getFullYear()}`;
    }
  }, [currentDate, viewMode]);

  // Render empty state
  if (calendarList.length === 0) {
    return (
      <div className="calendar-tab calendar-tab--empty">
        <div className="calendar-tab__empty-state">
          <span className="calendar-tab__empty-icon">📅</span>
          <p>No calendars found</p>
          <p className="calendar-tab__empty-hint">
            Create a calendar using <code>calendar_create</code> or import an iCal feed with <code>calendar_connect_ical</code>
          </p>
          {requestDomainState && (
            <button
              className="calendar-tab__refresh-button"
              onClick={handleSync}
            >
              🔄 Refresh
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="calendar-tab">
      {/* Header with navigation and view toggle */}
      <div className="calendar-tab__header">
        <div className="calendar-tab__nav">
          <button className="calendar-tab__nav-btn" onClick={handlePrevious}>
            ◀
          </button>
          <button className="calendar-tab__today-btn" onClick={handleToday}>
            Today
          </button>
          <button className="calendar-tab__nav-btn" onClick={handleNext}>
            ▶
          </button>
          <h2 className="calendar-tab__title">{headerTitle}</h2>
        </div>

        <div className="calendar-tab__controls">
          <div className="calendar-tab__view-toggle">
            <button
              className={`calendar-tab__view-btn ${viewMode === 'month' ? 'calendar-tab__view-btn--active' : ''}`}
              onClick={() => setViewMode('month')}
            >
              📅 Month
            </button>
            <button
              className={`calendar-tab__view-btn ${viewMode === 'gantt' ? 'calendar-tab__view-btn--active' : ''}`}
              onClick={() => setViewMode('gantt')}
            >
              📊 Gantt
            </button>
          </div>
          <button className="calendar-tab__sync-btn" onClick={handleSync} title="Refresh">
            🔄
          </button>
        </div>
      </div>

      {/* Calendar sidebar */}
      <div className="calendar-tab__content">
        <div className="calendar-tab__sidebar">
          <h3 className="calendar-tab__sidebar-title">Calendars</h3>
          {calendarList.map(calendar => (
            <div
              key={calendar.id}
              className="calendar-tab__calendar-item"
              onClick={() => toggleCalendarVisibility(calendar.id)}
            >
              <input
                type="checkbox"
                checked={visibleCalendarIds.has(calendar.id)}
                onChange={() => toggleCalendarVisibility(calendar.id)}
                className="calendar-tab__calendar-checkbox"
              />
              <span
                className="calendar-tab__calendar-color"
                style={{ backgroundColor: calendar.color }}
              />
              <span className="calendar-tab__calendar-name">{calendar.name}</span>
              {calendar.provider !== 'local' && (
                <span className="calendar-tab__calendar-badge">
                  {calendar.provider === 'ical' ? '📡' : '☁️'}
                </span>
              )}
              {calendar.syncStatus.state === 'syncing' && (
                <span className="calendar-tab__calendar-syncing">⟳</span>
              )}
              {calendar.syncStatus.state === 'error' && (
                <span className="calendar-tab__calendar-error" title={calendar.syncStatus.error}>⚠️</span>
              )}
            </div>
          ))}
        </div>

        {/* Main calendar view */}
        <div className="calendar-tab__main">
          {viewMode === 'month' ? (
            <MonthView
              events={visibleEvents}
              currentDate={currentDate}
              selectedEventId={selectedEventId}
              onEventClick={handleEventClick}
              onDateClick={(date) => setCurrentDate(date)}
            />
          ) : (
            <WeekGantt
              events={visibleEvents}
              currentDate={currentDate}
              selectedEventId={selectedEventId}
              onEventClick={handleEventClick}
            />
          )}
        </div>
      </div>

      {/* Event details panel (when selected) */}
      {selectedEventId && (() => {
        const selectedEvent = visibleEvents.find(e => e.id === selectedEventId);
        if (!selectedEvent) return null;

        const start = new Date(selectedEvent.start);
        const end = new Date(selectedEvent.end);

        return (
          <div className="calendar-tab__event-panel">
            <div className="calendar-tab__event-header">
              <span
                className="calendar-tab__event-color"
                style={{ backgroundColor: selectedEvent.calendarColor }}
              />
              <h3 className="calendar-tab__event-title">{selectedEvent.title}</h3>
              <button
                className="calendar-tab__event-close"
                onClick={() => setSelectedEventId(null)}
              >
                ✕
              </button>
            </div>
            <div className="calendar-tab__event-details">
              <div className="calendar-tab__event-time">
                {selectedEvent.allDay ? (
                  <span>All Day - {start.toLocaleDateString()}</span>
                ) : (
                  <span>
                    {start.toLocaleDateString()} {start.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    {' - '}
                    {end.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                )}
              </div>
              {selectedEvent.location && (
                <div className="calendar-tab__event-location">
                  📍 {selectedEvent.location}
                </div>
              )}
              {selectedEvent.description && (
                <div className="calendar-tab__event-description">
                  {selectedEvent.description}
                </div>
              )}
              <div className="calendar-tab__event-meta">
                <span>ID: {selectedEvent.id}</span>
                {selectedEvent.source !== 'local' && (
                  <span className="calendar-tab__event-source">
                    Source: {selectedEvent.source}
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

export default CalendarTab;
