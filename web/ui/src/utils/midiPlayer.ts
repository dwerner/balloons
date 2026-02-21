/**
 * MIDI Player - Web Audio synthesis for playing musical notes
 *
 * Notation format:
 * - Notes: C4, D#4, Eb5 (note name + octave)
 * - Rests: R
 * - Durations: :w (whole), :h (half), :q (quarter, default), :e (eighth), :s (sixteenth)
 * - Chords: [C4,E4,G4] (notes in brackets play simultaneously)
 *
 * Example: "C4 D4:h E4 [C4,E4,G4]:w R:q"
 */

export interface ParsedNote {
  note: string;
  frequency: number | null;  // null for rests
  frequencies?: number[];    // for chords
  duration: 'w' | 'h' | 'q' | 'e' | 's';
  durationBeats: number;
  isChord: boolean;
  isRest: boolean;
}

const NOTE_TO_SEMITONE: Record<string, number> = {
  'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11
};

const DURATION_TO_BEATS: Record<string, number> = {
  'w': 4,    // whole
  'h': 2,    // half
  'q': 1,    // quarter
  'e': 0.5,  // eighth
  's': 0.25, // sixteenth
};

/**
 * Convert a note name to frequency in Hz.
 * A4 = 440 Hz (MIDI note 69)
 */
export function noteToFrequency(note: string): number {
  const match = note.match(/^([A-Ga-g])([#b]?)(\d)$/);
  if (!match) {
    throw new Error(`Invalid note: ${note}`);
  }

  const noteName = match[1];
  const accidental = match[2];
  const octaveStr = match[3];

  if (!noteName || !octaveStr) {
    throw new Error(`Invalid note: ${note}`);
  }

  const octave = parseInt(octaveStr, 10);

  let semitone = NOTE_TO_SEMITONE[noteName.toUpperCase()];
  if (semitone === undefined) {
    throw new Error(`Unknown note: ${noteName}`);
  }

  if (accidental === '#') semitone += 1;
  if (accidental === 'b') semitone -= 1;

  // MIDI note number (C4 = 60, A4 = 69)
  const midiNote = (octave + 1) * 12 + semitone;

  // Frequency calculation: A4 (MIDI 69) = 440 Hz
  return 440 * Math.pow(2, (midiNote - 69) / 12);
}

/**
 * Parse a single note token like "C4", "C4:h", "[C4,E4,G4]:q", or "R"
 */
export function parseNoteToken(token: string): ParsedNote {
  token = token.trim();
  if (!token) {
    throw new Error('Empty token');
  }

  // Split note from duration
  let notePart: string;
  let duration: 'w' | 'h' | 'q' | 'e' | 's' = 'q';

  if (token.includes(':')) {
    const colonIdx = token.lastIndexOf(':');
    notePart = token.substring(0, colonIdx);
    const durPart = token.substring(colonIdx + 1).toLowerCase();
    if (!DURATION_TO_BEATS[durPart]) {
      throw new Error(`Invalid duration: ${durPart}`);
    }
    duration = durPart as typeof duration;
  } else {
    notePart = token;
  }

  const durationBeats = DURATION_TO_BEATS[duration] ?? 1;

  // Rest
  if (notePart.toUpperCase() === 'R') {
    return {
      note: 'R',
      frequency: null,
      duration,
      durationBeats,
      isChord: false,
      isRest: true,
    };
  }

  // Chord [C4,E4,G4]
  if (notePart.startsWith('[') && notePart.endsWith(']')) {
    const chordNotes = notePart.slice(1, -1).split(',').map(n => n.trim());
    if (chordNotes.length === 0) {
      throw new Error('Empty chord');
    }

    const frequencies = chordNotes.map(n => noteToFrequency(n));
    const primaryFreq = frequencies[0] ?? null;

    return {
      note: notePart,
      frequency: primaryFreq,
      frequencies,
      duration,
      durationBeats,
      isChord: true,
      isRest: false,
    };
  }

  // Single note
  const frequency = noteToFrequency(notePart);

  return {
    note: notePart,
    frequency,
    duration,
    durationBeats,
    isChord: false,
    isRest: false,
  };
}

/**
 * Parse a space-separated sequence of notes.
 */
export function parseNoteSequence(input: string): ParsedNote[] {
  const tokens = input.trim().split(/\s+/);
  if (tokens.length === 0 || (tokens.length === 1 && !tokens[0])) {
    throw new Error('Empty note sequence');
  }

  return tokens.map(parseNoteToken);
}

/**
 * Calculate total duration of a sequence in seconds.
 */
export function calculateDuration(notes: ParsedNote[], bpm: number): number {
  const totalBeats = notes.reduce((sum, note) => sum + note.durationBeats, 0);
  return (totalBeats / bpm) * 60;
}

export type OscillatorType = 'sine' | 'square' | 'sawtooth' | 'triangle';

/**
 * MIDI Synthesizer using Web Audio API
 */
export class MidiSynth {
  private ctx: AudioContext | null = null;
  private masterGain: GainNode | null = null;
  private isPlaying = false;
  private stopRequested = false;

  /**
   * Initialize or resume the audio context.
   * Must be called in response to user gesture (browser policy).
   */
  async initialize(): Promise<void> {
    if (!this.ctx) {
      this.ctx = new AudioContext();
      this.masterGain = this.ctx.createGain();
      this.masterGain.connect(this.ctx.destination);
    }

    if (this.ctx.state === 'suspended') {
      await this.ctx.resume();
    }
  }

  /**
   * Play a sequence of notes.
   */
  async playSequence(
    notes: ParsedNote[],
    bpm: number,
    waveform: OscillatorType = 'sine',
    volume: number = 0.5,
    onProgress?: (index: number, total: number) => void
  ): Promise<void> {
    await this.initialize();

    if (!this.ctx || !this.masterGain) {
      throw new Error('Audio context not initialized');
    }

    this.masterGain.gain.value = volume;
    this.isPlaying = true;
    this.stopRequested = false;

    const secondsPerBeat = 60 / bpm;
    let currentTime = this.ctx.currentTime + 0.05;  // Small buffer

    // Schedule all notes
    for (let i = 0; i < notes.length; i++) {
      if (this.stopRequested) break;

      const note = notes[i];
      if (!note) continue;

      const durationSeconds = note.durationBeats * secondsPerBeat;
      const noteDuration = durationSeconds * 0.85;  // Slight gap between notes

      if (note.isChord && note.frequencies) {
        // Play all chord notes simultaneously
        for (const freq of note.frequencies) {
          this.scheduleNote(freq, currentTime, noteDuration, waveform);
        }
      } else if (!note.isRest && note.frequency !== null) {
        // Single note
        this.scheduleNote(note.frequency, currentTime, noteDuration, waveform);
      }
      // Rests: just advance time without playing

      currentTime += durationSeconds;
    }

    // Wait for playback to complete
    const totalDuration = (currentTime - this.ctx.currentTime) * 1000;

    // Progress tracking
    if (onProgress) {
      const startTime = Date.now();
      const checkProgress = () => {
        if (!this.isPlaying) return;
        const elapsed = Date.now() - startTime;
        const progress = Math.min(elapsed / totalDuration, 1);
        const currentIndex = Math.floor(progress * notes.length);
        onProgress(currentIndex, notes.length);
        if (progress < 1) {
          requestAnimationFrame(checkProgress);
        }
      };
      checkProgress();
    }

    await new Promise(resolve => setTimeout(resolve, totalDuration));
    this.isPlaying = false;
  }

  /**
   * Schedule a single note to play.
   */
  private scheduleNote(
    frequency: number,
    startTime: number,
    duration: number,
    waveform: OscillatorType
  ): void {
    if (!this.ctx || !this.masterGain) return;

    const osc = this.ctx.createOscillator();
    const gain = this.ctx.createGain();

    osc.type = waveform;
    osc.frequency.value = frequency;

    // ADSR-like envelope for more natural sound
    const attackTime = Math.min(0.02, duration * 0.1);
    const decayTime = Math.min(0.05, duration * 0.2);
    const sustainLevel = 0.7;
    const releaseTime = Math.min(0.1, duration * 0.2);

    gain.gain.setValueAtTime(0, startTime);
    // Attack
    gain.gain.linearRampToValueAtTime(1, startTime + attackTime);
    // Decay to sustain
    gain.gain.linearRampToValueAtTime(sustainLevel, startTime + attackTime + decayTime);
    // Sustain (held at sustainLevel)
    // Release
    gain.gain.setValueAtTime(sustainLevel, startTime + duration - releaseTime);
    gain.gain.exponentialRampToValueAtTime(0.001, startTime + duration);

    osc.connect(gain);
    gain.connect(this.masterGain);

    osc.start(startTime);
    osc.stop(startTime + duration + 0.01);  // Small buffer to avoid clicks
  }

  /**
   * Stop playback.
   */
  stop(): void {
    this.stopRequested = true;
    this.isPlaying = false;
  }

  /**
   * Check if currently playing.
   */
  get playing(): boolean {
    return this.isPlaying;
  }

  /**
   * Clean up resources.
   */
  dispose(): void {
    this.stop();
    if (this.ctx) {
      this.ctx.close();
      this.ctx = null;
      this.masterGain = null;
    }
  }
}

// Singleton instance for global use
let synthInstance: MidiSynth | null = null;

export function getMidiSynth(): MidiSynth {
  if (!synthInstance) {
    synthInstance = new MidiSynth();
  }
  return synthInstance;
}
