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
  /** Call a @ws_expose method on a domain plugin */
  callDomainMethod?: (
    methodName: string,
    params?: Record<string, unknown> | null
  ) => Promise<Record<string, unknown>>;
}

// Event form state
interface EventFormData {
  title: string;
  date: string;
  startTime: string;
  endTime: string;
  description: string;
  location: string;
  allDay: boolean;
  calendarId: string;
}

const defaultEventForm = (): EventFormData => {
  const now = new Date();
  const dateStr = now.toISOString().split('T')[0];
  const hour = now.getHours();
  const startTime = `${String(hour).padStart(2, '0')}:00`;
  const endTime = `${String(hour + 1).padStart(2, '0')}:00`;
  return {
    title: '',
    date: dateStr,
    startTime,
    endTime,
    description: '',
    location: '',
    allDay: false,
    calendarId: '',
  };
};

export function CalendarTab({
  sendMessage,
  sessionId,
  subscribeToDomainEvents,
  requestDomainState,
  isLLMResponding = false,
  callDomainMethod,
}: CalendarTabProps) {
  const [calendars, setCalendars] = useState<Map<string, Calendar>>(new Map());
  const [viewMode, setViewMode] = useState<ViewMode>('month');
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [visibleCalendarIds, setVisibleCalendarIds] = useState<Set<string>>(new Set());
  const [showEventForm, setShowEventForm] = useState(false);
  const [eventForm, setEventForm] = useState<EventFormData>(defaultEventForm());
  const [editingEventId, setEditingEventId] = useState<string | null>(null); // null = create mode, string = edit mode
  const [showCalendarForm, setShowCalendarForm] = useState(false);
  const [calendarForm, setCalendarForm] = useState({ name: '', color: '#4285f4' });
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Preview state - persists while form is open
  const [previewEvent, setPreviewEvent] = useState<{
    date: Date;
    startTime?: string;
    endTime?: string;
    dayIndex?: number;
  } | null>(null);

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

  // Get local calendars (where we can add events)
  const localCalendars = useMemo(() =>
    calendarList.filter(c => c.provider === 'local'),
    [calendarList]
  );

  // Open add event form (from month view click)
  const handleAddEvent = useCallback((date?: Date) => {
    const form = defaultEventForm();
    if (date) {
      form.date = date.toISOString().split('T')[0];
      // Set preview for month view
      setPreviewEvent({ date });
    }
    if (localCalendars.length > 0) {
      form.calendarId = localCalendars[0].id;
    }
    setEventForm(form);
    setShowEventForm(true);
  }, [localCalendars]);

  // Open add event form (from gantt drag)
  const handleAddEventFromDrag = useCallback((date: Date, startTime: string, endTime: string, dayIndex: number) => {
    const form = defaultEventForm();
    form.date = date.toISOString().split('T')[0];
    form.startTime = startTime;
    form.endTime = endTime;
    form.allDay = false;
    if (localCalendars.length > 0) {
      form.calendarId = localCalendars[0].id;
    }
    // Set preview for gantt view
    setPreviewEvent({ date, startTime, endTime, dayIndex });
    setEventForm(form);
    setShowEventForm(true);
  }, [localCalendars]);

  // Cancel event form - clear preview
  const handleCancelEventForm = useCallback(() => {
    setShowEventForm(false);
    setPreviewEvent(null);
    setEditingEventId(null);
  }, []);

  // Open edit form for an existing event
  const handleEditEvent = useCallback((event: CalendarEvent & { calendarId: string }) => {
    const startDate = new Date(event.start);
    const endDate = new Date(event.end);

    const form: EventFormData = {
      title: event.title,
      date: startDate.toISOString().split('T')[0],
      startTime: `${String(startDate.getHours()).padStart(2, '0')}:${String(startDate.getMinutes()).padStart(2, '0')}`,
      endTime: `${String(endDate.getHours()).padStart(2, '0')}:${String(endDate.getMinutes()).padStart(2, '0')}`,
      description: event.description || '',
      location: event.location || '',
      allDay: event.allDay || false,
      calendarId: event.calendarId,
    };

    setEventForm(form);
    setEditingEventId(event.id);
    setShowEventForm(true);
    setSelectedEventId(null); // Close the details panel
  }, []);

  // Submit event (create or update)
  const handleSubmitEvent = useCallback(async () => {
    if (!callDomainMethod || !eventForm.title.trim()) return;
    if (!editingEventId && !eventForm.calendarId) return; // Need calendar for create

    let start: string;
    let end: string;

    if (eventForm.allDay) {
      start = eventForm.date;
      // For all-day, end is the next day
      const endDate = new Date(eventForm.date);
      endDate.setDate(endDate.getDate() + 1);
      end = endDate.toISOString().split('T')[0];
    } else {
      start = `${eventForm.date}T${eventForm.startTime}:00`;
      end = `${eventForm.date}T${eventForm.endTime}:00`;
    }

    setIsSubmitting(true);
    try {
      if (editingEventId) {
        // Update existing event
        await callDomainMethod('calendarUpdateEvent', {
          event_id: editingEventId,
          title: eventForm.title,
          start,
          end,
          description: eventForm.description.trim() || undefined,
          location: eventForm.location.trim() || undefined,
        });
      } else {
        // Create new event
        await callDomainMethod('calendarCreateEvent', {
          calendar_id: eventForm.calendarId,
          title: eventForm.title,
          start,
          end,
          all_day: eventForm.allDay || undefined,
          description: eventForm.description.trim() || undefined,
          location: eventForm.location.trim() || undefined,
        });
      }
      setShowEventForm(false);
      setEventForm(defaultEventForm());
      setPreviewEvent(null);
      setEditingEventId(null);
    } catch (e) {
      console.error('[CalendarTab] Failed to save event:', e);
    } finally {
      setIsSubmitting(false);
    }
  }, [callDomainMethod, eventForm, editingEventId]);

  // Submit calendar via LLM
  const handleSubmitCalendar = useCallback(async () => {
    if (!callDomainMethod || !calendarForm.name.trim()) return;

    setIsSubmitting(true);
    try {
      await callDomainMethod('calendarCreate', {
        name: calendarForm.name,
        color: calendarForm.color || undefined,
      });
      setShowCalendarForm(false);
      setCalendarForm({ name: '', color: '#4285f4' });
    } catch (e) {
      console.error('[CalendarTab] Failed to create calendar:', e);
    } finally {
      setIsSubmitting(false);
    }
  }, [callDomainMethod, calendarForm]);

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
            Create a calendar to get started
          </p>
          <div className="calendar-tab__empty-actions">
            {callDomainMethod && (
              <button
                className="calendar-tab__btn calendar-tab__btn--primary"
                onClick={() => setShowCalendarForm(true)}
              >
                + Create Calendar
              </button>
            )}
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

        {/* Create Calendar Modal (shown in empty state too) */}
        {showCalendarForm && (
          <div className="calendar-tab__modal-overlay" onClick={() => setShowCalendarForm(false)}>
            <div className="calendar-tab__modal calendar-tab__modal--small" onClick={e => e.stopPropagation()}>
              <div className="calendar-tab__modal-header">
                <h3>Create Calendar</h3>
                <button
                  className="calendar-tab__modal-close"
                  onClick={() => setShowCalendarForm(false)}
                >
                  ✕
                </button>
              </div>
              <div className="calendar-tab__modal-body">
                <div className="calendar-tab__form-group">
                  <label>Name *</label>
                  <input
                    type="text"
                    value={calendarForm.name}
                    onChange={e => setCalendarForm(f => ({ ...f, name: e.target.value }))}
                    placeholder="e.g., Work, Personal"
                    autoFocus
                  />
                </div>
                <div className="calendar-tab__form-group">
                  <label>Color</label>
                  <div className="calendar-tab__color-picker">
                    <input
                      type="color"
                      value={calendarForm.color}
                      onChange={e => setCalendarForm(f => ({ ...f, color: e.target.value }))}
                    />
                    <input
                      type="text"
                      value={calendarForm.color}
                      onChange={e => setCalendarForm(f => ({ ...f, color: e.target.value }))}
                      placeholder="#4285f4"
                    />
                  </div>
                </div>
              </div>
              <div className="calendar-tab__modal-footer">
                <button
                  className="calendar-tab__btn calendar-tab__btn--secondary"
                  onClick={() => setShowCalendarForm(false)}
                >
                  Cancel
                </button>
                <button
                  className="calendar-tab__btn calendar-tab__btn--primary"
                  onClick={handleSubmitCalendar}
                  disabled={!calendarForm.name.trim() || isSubmitting}
                >
                  {isSubmitting ? 'Creating...' : 'Create'}
                </button>
              </div>
            </div>
          </div>
        )}
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
          {localCalendars.length > 0 && callDomainMethod && (
            <button
              className="calendar-tab__add-btn"
              onClick={() => handleAddEvent()}
              title="Add Event"
            >
              + Add Event
            </button>
          )}
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
          <div className="calendar-tab__sidebar-header">
            <h3 className="calendar-tab__sidebar-title">Calendars</h3>
            {callDomainMethod && (
              <button
                className="calendar-tab__sidebar-add"
                onClick={() => setShowCalendarForm(true)}
                title="Create Calendar"
              >
                +
              </button>
            )}
          </div>
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
              onDateClick={(date) => {
                // If we have local calendars, open add event form; otherwise just navigate
                if (localCalendars.length > 0 && callDomainMethod) {
                  handleAddEvent(date);
                } else {
                  setCurrentDate(date);
                }
              }}
              previewDate={previewEvent?.date}
            />
          ) : (
            <WeekGantt
              events={visibleEvents}
              currentDate={currentDate}
              selectedEventId={selectedEventId}
              onEventClick={handleEventClick}
              onCreateEvent={localCalendars.length > 0 && callDomainMethod
                ? (date, startTime, endTime, dayIndex) => handleAddEventFromDrag(date, startTime, endTime, dayIndex)
                : undefined}
              previewEvent={previewEvent?.dayIndex !== undefined ? {
                dayIndex: previewEvent.dayIndex,
                startTime: previewEvent.startTime!,
                endTime: previewEvent.endTime!,
              } : undefined}
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
        const isEditable = selectedEvent.source === 'local' && callDomainMethod;

        return (
          <div className="calendar-tab__event-panel">
            <div className="calendar-tab__event-header">
              <span
                className="calendar-tab__event-color"
                style={{ backgroundColor: selectedEvent.calendarColor }}
              />
              <h3 className="calendar-tab__event-title">{selectedEvent.title}</h3>
              <div className="calendar-tab__event-actions">
                {isEditable && (
                  <button
                    className="calendar-tab__event-edit"
                    onClick={() => handleEditEvent(selectedEvent)}
                    title="Edit event"
                  >
                    ✏️
                  </button>
                )}
                <button
                  className="calendar-tab__event-close"
                  onClick={() => setSelectedEventId(null)}
                >
                  ✕
                </button>
              </div>
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

      {/* Create Calendar Modal */}
      {showCalendarForm && (
        <div className="calendar-tab__modal-overlay" onClick={() => setShowCalendarForm(false)}>
          <div className="calendar-tab__modal calendar-tab__modal--small" onClick={e => e.stopPropagation()}>
            <div className="calendar-tab__modal-header">
              <h3>Create Calendar</h3>
              <button
                className="calendar-tab__modal-close"
                onClick={() => setShowCalendarForm(false)}
              >
                ✕
              </button>
            </div>
            <div className="calendar-tab__modal-body">
              <div className="calendar-tab__form-group">
                <label>Name *</label>
                <input
                  type="text"
                  value={calendarForm.name}
                  onChange={e => setCalendarForm(f => ({ ...f, name: e.target.value }))}
                  placeholder="e.g., Work, Personal"
                  autoFocus
                />
              </div>
              <div className="calendar-tab__form-group">
                <label>Color</label>
                <div className="calendar-tab__color-picker">
                  <input
                    type="color"
                    value={calendarForm.color}
                    onChange={e => setCalendarForm(f => ({ ...f, color: e.target.value }))}
                  />
                  <input
                    type="text"
                    value={calendarForm.color}
                    onChange={e => setCalendarForm(f => ({ ...f, color: e.target.value }))}
                    placeholder="#4285f4"
                  />
                </div>
              </div>
            </div>
            <div className="calendar-tab__modal-footer">
              <button
                className="calendar-tab__btn calendar-tab__btn--secondary"
                onClick={() => setShowCalendarForm(false)}
              >
                Cancel
              </button>
              <button
                className="calendar-tab__btn calendar-tab__btn--primary"
                onClick={handleSubmitCalendar}
                disabled={!calendarForm.name.trim() || isLLMResponding}
              >
                {isLLMResponding ? 'Creating...' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Add/Edit Event Modal */}
      {showEventForm && (
        <div className="calendar-tab__modal-overlay" onClick={handleCancelEventForm}>
          <div className="calendar-tab__modal" onClick={e => e.stopPropagation()}>
            <div className="calendar-tab__modal-header">
              <h3>{editingEventId ? 'Edit Event' : 'Add Event'}</h3>
              <button
                className="calendar-tab__modal-close"
                onClick={handleCancelEventForm}
              >
                ✕
              </button>
            </div>
            <div className="calendar-tab__modal-body">
              <div className="calendar-tab__form-group">
                <label>Title *</label>
                <input
                  type="text"
                  value={eventForm.title}
                  onChange={e => setEventForm(f => ({ ...f, title: e.target.value }))}
                  placeholder="Event title"
                  autoFocus
                />
              </div>

              {/* Only show calendar selector when creating, not editing */}
              {!editingEventId && (
                <div className="calendar-tab__form-group">
                  <label>Calendar *</label>
                  <select
                    value={eventForm.calendarId}
                    onChange={e => setEventForm(f => ({ ...f, calendarId: e.target.value }))}
                  >
                    {localCalendars.map(cal => (
                      <option key={cal.id} value={cal.id}>{cal.name}</option>
                    ))}
                  </select>
                </div>
              )}

              <div className="calendar-tab__form-group">
                <label>Date *</label>
                <input
                  type="date"
                  value={eventForm.date}
                  onChange={e => setEventForm(f => ({ ...f, date: e.target.value }))}
                />
              </div>

              <div className="calendar-tab__form-row">
                <label className="calendar-tab__checkbox-label">
                  <input
                    type="checkbox"
                    checked={eventForm.allDay}
                    onChange={e => setEventForm(f => ({ ...f, allDay: e.target.checked }))}
                  />
                  All day
                </label>
              </div>

              {!eventForm.allDay && (
                <div className="calendar-tab__form-row">
                  <div className="calendar-tab__form-group calendar-tab__form-group--half">
                    <label>Start Time</label>
                    <input
                      type="time"
                      value={eventForm.startTime}
                      onChange={e => setEventForm(f => ({ ...f, startTime: e.target.value }))}
                    />
                  </div>
                  <div className="calendar-tab__form-group calendar-tab__form-group--half">
                    <label>End Time</label>
                    <input
                      type="time"
                      value={eventForm.endTime}
                      onChange={e => setEventForm(f => ({ ...f, endTime: e.target.value }))}
                    />
                  </div>
                </div>
              )}

              <div className="calendar-tab__form-group">
                <label>Location</label>
                <input
                  type="text"
                  value={eventForm.location}
                  onChange={e => setEventForm(f => ({ ...f, location: e.target.value }))}
                  placeholder="Location (optional)"
                />
              </div>

              <div className="calendar-tab__form-group">
                <label>Description</label>
                <textarea
                  value={eventForm.description}
                  onChange={e => setEventForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="Description (optional)"
                  rows={3}
                />
              </div>
            </div>
            <div className="calendar-tab__modal-footer">
              <button
                className="calendar-tab__btn calendar-tab__btn--secondary"
                onClick={handleCancelEventForm}
              >
                Cancel
              </button>
              <button
                className="calendar-tab__btn calendar-tab__btn--primary"
                onClick={handleSubmitEvent}
                disabled={!eventForm.title.trim() || (!editingEventId && !eventForm.calendarId) || isSubmitting}
              >
                {isSubmitting ? 'Saving...' : (editingEventId ? 'Save Changes' : 'Create Event')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CalendarTab;
