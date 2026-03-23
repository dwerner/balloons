/**
 * WeekGantt - Weekly Gantt chart view
 *
 * Shows events as horizontal bars spanning their duration across days.
 * Great for visualizing multi-day events and scheduling conflicts.
 * Supports drag-to-create for quick event creation.
 */

import React, { useMemo, useState, useCallback, useRef } from 'react';
import { CalendarEvent } from './types';

interface EventWithCalendar extends CalendarEvent {
  calendarId: string;
  calendarColor: string;
}

interface DragState {
  dayIndex: number;
  startHour: number;
  endHour: number;
}

interface PreviewEvent {
  dayIndex: number;
  startTime: string;
  endTime: string;
}

interface WeekGanttProps {
  events: EventWithCalendar[];
  currentDate: Date;
  selectedEventId: string | null;
  onEventClick: (eventId: string) => void;
  /** Called when user drags to create an event. Passes date, start time, end time, and day index. */
  onCreateEvent?: (date: Date, startTime: string, endTime: string, dayIndex: number) => void;
  /** Persistent preview to show while modal is open */
  previewEvent?: PreviewEvent;
}

// Hours to display (6 AM to 10 PM)
const START_HOUR = 6;
const END_HOUR = 22;
const HOURS = Array.from({ length: END_HOUR - START_HOUR + 1 }, (_, i) => i + START_HOUR);

export function WeekGantt({
  events,
  currentDate,
  selectedEventId,
  onEventClick,
  onCreateEvent,
  previewEvent,
}: WeekGanttProps) {
  // Drag state for creating events
  const [dragState, setDragState] = useState<DragState | null>(null);
  const isDragging = useRef(false);
  const dragStartY = useRef(0);
  const dragDayIndex = useRef(0);
  // Calculate the week's days
  const weekDays = useMemo(() => {
    const days: Date[] = [];
    const weekStart = new Date(currentDate);
    weekStart.setDate(weekStart.getDate() - weekStart.getDay());
    weekStart.setHours(0, 0, 0, 0);

    for (let i = 0; i < 7; i++) {
      const day = new Date(weekStart);
      day.setDate(day.getDate() + i);
      days.push(day);
    }
    return days;
  }, [currentDate]);

  // Get the week boundaries
  const { weekStart, weekEnd } = useMemo(() => {
    const start = new Date(weekDays[0]);
    start.setHours(START_HOUR, 0, 0, 0);
    const end = new Date(weekDays[6]);
    end.setHours(END_HOUR, 59, 59, 999);
    return { weekStart: start, weekEnd: end };
  }, [weekDays]);

  // Filter and position events for this week
  const positionedEvents = useMemo(() => {
    const weekEvents = events.filter(event => {
      const eventStart = new Date(event.start);
      const eventEnd = new Date(event.end);
      return eventStart <= weekEnd && eventEnd >= weekStart;
    });

    // Group all-day events separately
    const allDayEvents: EventWithCalendar[] = [];
    const timedEvents: EventWithCalendar[] = [];

    weekEvents.forEach(event => {
      if (event.allDay) {
        allDayEvents.push(event);
      } else {
        timedEvents.push(event);
      }
    });

    return { allDayEvents, timedEvents };
  }, [events, weekStart, weekEnd]);

  // Calculate position for an event
  const getEventPosition = (event: EventWithCalendar) => {
    const eventStart = new Date(event.start);
    const eventEnd = new Date(event.end);

    // Clamp to week boundaries
    const clampedStart = new Date(Math.max(eventStart.getTime(), weekStart.getTime()));
    const clampedEnd = new Date(Math.min(eventEnd.getTime(), weekEnd.getTime()));

    // Calculate day index
    const startDayIndex = Math.floor(
      (clampedStart.getTime() - weekDays[0].getTime()) / (24 * 60 * 60 * 1000)
    );

    // Calculate time position within day
    const startHour = clampedStart.getHours() + clampedStart.getMinutes() / 60;
    const endHour = clampedEnd.getHours() + clampedEnd.getMinutes() / 60;

    // Clamp hours to visible range
    const visibleStartHour = Math.max(startHour, START_HOUR);
    const visibleEndHour = Math.min(endHour, END_HOUR);

    // Calculate percentages for single day
    const hourRange = END_HOUR - START_HOUR;
    const top = ((visibleStartHour - START_HOUR) / hourRange) * 100;
    const height = ((visibleEndHour - visibleStartHour) / hourRange) * 100;

    return {
      dayIndex: Math.max(0, Math.min(6, startDayIndex)),
      top: `${Math.max(0, top)}%`,
      height: `${Math.max(2, height)}%`, // Minimum height for visibility
    };
  };

  // Calculate position for all-day events
  const getAllDayEventPosition = (event: EventWithCalendar) => {
    const eventStart = new Date(event.start);
    const eventEnd = new Date(event.end);

    // Find start and end day indices
    let startDayIndex = 0;
    let endDayIndex = 6;

    for (let i = 0; i < 7; i++) {
      const dayStart = weekDays[i];
      const dayEnd = new Date(dayStart);
      dayEnd.setHours(23, 59, 59, 999);

      if (eventStart <= dayEnd && startDayIndex === 0) {
        startDayIndex = i;
      }
      if (eventEnd >= dayStart) {
        endDayIndex = i;
      }
    }

    const left = (startDayIndex / 7) * 100;
    const width = ((endDayIndex - startDayIndex + 1) / 7) * 100;

    return {
      left: `${left}%`,
      width: `${Math.max(width, 14.28)}%`, // Minimum 1 day width
    };
  };

  // Check if a day is today
  const isToday = (day: Date): boolean => {
    const today = new Date();
    return (
      day.getDate() === today.getDate() &&
      day.getMonth() === today.getMonth() &&
      day.getFullYear() === today.getFullYear()
    );
  };

  // Format hour for display
  const formatHour = (hour: number): string => {
    if (hour === 0) return '12 AM';
    if (hour === 12) return '12 PM';
    if (hour > 12) return `${hour - 12} PM`;
    return `${hour} AM`;
  };

  // Format time as HH:MM
  const formatTimeStr = (hour: number): string => {
    const h = Math.floor(hour);
    const m = Math.round((hour - h) * 60);
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
  };

  // Get hour from Y position within the time grid
  const getHourFromY = useCallback((y: number, element: HTMLElement): number => {
    const rect = element.getBoundingClientRect();
    const relativeY = y - rect.top;
    // The column has HOURS.length slots, each representing one hour starting at that hour
    // So total height represents HOURS.length hours
    const percentage = relativeY / rect.height;
    const hour = START_HOUR + (percentage * HOURS.length);
    // Snap to 15-minute increments and clamp to valid range
    const snapped = Math.round(hour * 4) / 4;
    return Math.max(START_HOUR, Math.min(END_HOUR, snapped));
  }, []);

  // Handle mouse down on day column
  const handleMouseDown = useCallback((e: React.MouseEvent, dayIndex: number) => {
    if (!onCreateEvent) return;
    if ((e.target as HTMLElement).closest('.week-gantt__event')) return; // Don't start drag on events

    const column = e.currentTarget as HTMLElement;
    const hour = getHourFromY(e.clientY, column);

    isDragging.current = true;
    dragStartY.current = hour;
    dragDayIndex.current = dayIndex;

    setDragState({
      dayIndex,
      startHour: hour,
      endHour: hour + 0.5, // Default 30 min
    });
  }, [onCreateEvent, getHourFromY]);

  // Handle mouse move
  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging.current || !dragState) return;

    const column = e.currentTarget as HTMLElement;
    const hour = getHourFromY(e.clientY, column);

    // Update drag state based on direction
    const startHour = Math.min(dragStartY.current, hour);
    const endHour = Math.max(dragStartY.current, hour);

    setDragState({
      ...dragState,
      startHour: Math.max(START_HOUR, startHour),
      endHour: Math.min(END_HOUR, Math.max(endHour, startHour + 0.25)),
    });
  }, [dragState, getHourFromY]);

  // Handle mouse up
  const handleMouseUp = useCallback(() => {
    if (!isDragging.current || !dragState || !onCreateEvent) {
      isDragging.current = false;
      setDragState(null);
      return;
    }

    const date = weekDays[dragState.dayIndex];
    const startTime = formatTimeStr(dragState.startHour);
    const endTime = formatTimeStr(dragState.endHour);

    const dayIndex = dragState.dayIndex;
    isDragging.current = false;
    setDragState(null);

    onCreateEvent(date, startTime, endTime, dayIndex);
  }, [dragState, weekDays, onCreateEvent]);

  // Handle mouse leave (cancel drag)
  const handleMouseLeave = useCallback(() => {
    if (isDragging.current) {
      isDragging.current = false;
      setDragState(null);
    }
  }, []);

  return (
    <div className="week-gantt">
      {/* Header with day names */}
      <div className="week-gantt__header">
        <div className="week-gantt__time-column"></div>
        {weekDays.map((day, index) => (
          <div
            key={index}
            className={`week-gantt__day-header ${isToday(day) ? 'week-gantt__day-header--today' : ''}`}
          >
            <span className="week-gantt__day-name">
              {day.toLocaleDateString('en-US', { weekday: 'short' })}
            </span>
            <span className="week-gantt__day-date">
              {day.getDate()}
            </span>
          </div>
        ))}
      </div>

      {/* All-day events section */}
      {positionedEvents.allDayEvents.length > 0 && (
        <div className="week-gantt__all-day">
          <div className="week-gantt__time-column">
            <span className="week-gantt__time-label">All Day</span>
          </div>
          <div className="week-gantt__all-day-grid">
            {positionedEvents.allDayEvents.map(event => {
              const position = getAllDayEventPosition(event);
              return (
                <div
                  key={event.id}
                  className={`week-gantt__all-day-event ${
                    event.id === selectedEventId ? 'week-gantt__event--selected' : ''
                  }`}
                  style={{
                    left: position.left,
                    width: position.width,
                    backgroundColor: event.calendarColor,
                  }}
                  onClick={() => onEventClick(event.id)}
                  title={event.title}
                >
                  <span className="week-gantt__event-title">{event.title}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Time grid */}
      <div className="week-gantt__body">
        {/* Time labels */}
        <div className="week-gantt__time-column">
          {HOURS.map(hour => (
            <div key={hour} className="week-gantt__time-slot">
              <span className="week-gantt__time-label">{formatHour(hour)}</span>
            </div>
          ))}
        </div>

        {/* Day columns */}
        <div className="week-gantt__grid">
          {weekDays.map((day, dayIndex) => (
            <div
              key={dayIndex}
              className={`week-gantt__day-column ${isToday(day) ? 'week-gantt__day-column--today' : ''} ${onCreateEvent ? 'week-gantt__day-column--draggable' : ''}`}
              onMouseDown={(e) => handleMouseDown(e, dayIndex)}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={handleMouseLeave}
            >
              {/* Hour grid lines */}
              {HOURS.map(hour => (
                <div key={hour} className="week-gantt__hour-slot" />
              ))}

              {/* Drag preview (during drag) */}
              {dragState && dragState.dayIndex === dayIndex && (
                <div
                  className="week-gantt__drag-preview"
                  style={{
                    top: `${((dragState.startHour - START_HOUR) / (END_HOUR - START_HOUR)) * 100}%`,
                    height: `${((dragState.endHour - dragState.startHour) / (END_HOUR - START_HOUR)) * 100}%`,
                  }}
                >
                  <span className="week-gantt__drag-time">
                    {formatHour(Math.floor(dragState.startHour))} - {formatHour(Math.floor(dragState.endHour))}
                  </span>
                </div>
              )}

              {/* Persistent preview (while modal is open) */}
              {!dragState && previewEvent && previewEvent.dayIndex === dayIndex && (() => {
                const [sh, sm] = previewEvent.startTime.split(':').map(Number);
                const [eh, em] = previewEvent.endTime.split(':').map(Number);
                const startHour = sh + sm / 60;
                const endHour = eh + em / 60;
                return (
                  <div
                    className="week-gantt__drag-preview week-gantt__drag-preview--persistent"
                    style={{
                      top: `${((startHour - START_HOUR) / (END_HOUR - START_HOUR)) * 100}%`,
                      height: `${((endHour - startHour) / (END_HOUR - START_HOUR)) * 100}%`,
                    }}
                  >
                    <span className="week-gantt__drag-time">New event...</span>
                  </div>
                );
              })()}

              {/* Events for this day */}
              {positionedEvents.timedEvents
                .filter(event => {
                  const pos = getEventPosition(event);
                  return pos.dayIndex === dayIndex;
                })
                .map(event => {
                  const position = getEventPosition(event);
                  return (
                    <div
                      key={event.id}
                      className={`week-gantt__event ${
                        event.id === selectedEventId ? 'week-gantt__event--selected' : ''
                      }`}
                      style={{
                        top: position.top,
                        height: position.height,
                        backgroundColor: event.calendarColor,
                      }}
                      onClick={() => onEventClick(event.id)}
                      title={`${event.title} - ${new Date(event.start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`}
                    >
                      <span className="week-gantt__event-time">
                        {new Date(event.start).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
                      </span>
                      <span className="week-gantt__event-title">{event.title}</span>
                    </div>
                  );
                })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default WeekGantt;
