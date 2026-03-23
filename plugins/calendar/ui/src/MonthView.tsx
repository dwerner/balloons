/**
 * MonthView - Traditional month calendar grid
 *
 * Shows a 7-column grid with events displayed as colored blocks.
 */

import React, { useMemo } from 'react';
import { CalendarEvent } from './types';

interface EventWithCalendar extends CalendarEvent {
  calendarId: string;
  calendarColor: string;
}

interface MonthViewProps {
  events: EventWithCalendar[];
  currentDate: Date;
  selectedEventId: string | null;
  onEventClick: (eventId: string) => void;
  onDateClick: (date: Date) => void;
  /** Date to show preview indicator on (when form is open) */
  previewDate?: Date;
}

// Days of the week headers
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

// Check if two dates are the same day
const isSameDay = (a: Date, b: Date): boolean =>
  a.getDate() === b.getDate() &&
  a.getMonth() === b.getMonth() &&
  a.getFullYear() === b.getFullYear();

export function MonthView({
  events,
  currentDate,
  selectedEventId,
  onEventClick,
  onDateClick,
  previewDate,
}: MonthViewProps) {
  // Calculate the days to display in the month grid
  const { weeks, monthStart, monthEnd } = useMemo(() => {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();

    // First and last day of the month
    const monthStart = new Date(year, month, 1);
    const monthEnd = new Date(year, month + 1, 0);

    // Start from the Sunday of the week containing the 1st
    const gridStart = new Date(monthStart);
    gridStart.setDate(gridStart.getDate() - gridStart.getDay());

    // End on the Saturday of the week containing the last day
    const gridEnd = new Date(monthEnd);
    gridEnd.setDate(gridEnd.getDate() + (6 - gridEnd.getDay()));

    // Build weeks array
    const weeks: Date[][] = [];
    let currentWeek: Date[] = [];
    const cursor = new Date(gridStart);

    while (cursor <= gridEnd) {
      currentWeek.push(new Date(cursor));
      if (currentWeek.length === 7) {
        weeks.push(currentWeek);
        currentWeek = [];
      }
      cursor.setDate(cursor.getDate() + 1);
    }

    return { weeks, monthStart, monthEnd };
  }, [currentDate]);

  // Get events for a specific day
  const getEventsForDay = (day: Date): EventWithCalendar[] => {
    const dayStart = new Date(day);
    dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(day);
    dayEnd.setHours(23, 59, 59, 999);

    return events.filter(event => {
      const eventStart = new Date(event.start);
      const eventEnd = new Date(event.end);
      // Event overlaps with this day
      return eventStart <= dayEnd && eventEnd >= dayStart;
    }).sort((a, b) => {
      // Sort all-day events first, then by start time
      if (a.allDay && !b.allDay) return -1;
      if (!a.allDay && b.allDay) return 1;
      return new Date(a.start).getTime() - new Date(b.start).getTime();
    });
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

  // Check if a day is in the current month
  const isCurrentMonth = (day: Date): boolean => {
    return day.getMonth() === currentDate.getMonth();
  };

  // Format time for display
  const formatTime = (dateStr: string): string => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  };

  return (
    <div className="month-view">
      {/* Day headers */}
      <div className="month-view__header">
        {DAYS.map(day => (
          <div key={day} className="month-view__day-header">
            {day}
          </div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="month-view__grid">
        {weeks.map((week, weekIndex) => (
          <div key={weekIndex} className="month-view__week">
            {week.map((day, dayIndex) => {
              const dayEvents = getEventsForDay(day);
              const maxVisibleEvents = 3;
              const hiddenCount = Math.max(0, dayEvents.length - maxVisibleEvents);

              return (
                <div
                  key={dayIndex}
                  className={`month-view__day ${
                    !isCurrentMonth(day) ? 'month-view__day--other-month' : ''
                  } ${isToday(day) ? 'month-view__day--today' : ''} ${
                    previewDate && isSameDay(day, previewDate) ? 'month-view__day--preview' : ''
                  }`}
                  onClick={() => onDateClick(day)}
                >
                  <div className="month-view__day-number">
                    {day.getDate()}
                  </div>
                  {/* Preview indicator */}
                  {previewDate && isSameDay(day, previewDate) && (
                    <div className="month-view__preview">
                      <span>New event...</span>
                    </div>
                  )}
                  <div className="month-view__day-events">
                    {dayEvents.slice(0, maxVisibleEvents).map(event => (
                      <div
                        key={event.id}
                        className={`month-view__event ${
                          event.allDay ? 'month-view__event--all-day' : ''
                        } ${event.id === selectedEventId ? 'month-view__event--selected' : ''}`}
                        style={{
                          backgroundColor: event.calendarColor,
                          borderColor: event.calendarColor,
                        }}
                        onClick={(e) => {
                          e.stopPropagation();
                          onEventClick(event.id);
                        }}
                        title={`${event.title}${event.allDay ? ' (All day)' : ` at ${formatTime(event.start)}`}`}
                      >
                        {!event.allDay && (
                          <span className="month-view__event-time">
                            {formatTime(event.start)}
                          </span>
                        )}
                        <span className="month-view__event-title">
                          {event.title}
                        </span>
                      </div>
                    ))}
                    {hiddenCount > 0 && (
                      <div className="month-view__more-events">
                        +{hiddenCount} more
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

export default MonthView;
