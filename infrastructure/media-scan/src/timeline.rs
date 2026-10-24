use serde::{Deserialize, Serialize};
use std::cmp::{Ordering, Reverse};
use std::collections::BinaryHeap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Gap {
    pub from_seconds: f64,
    pub to_seconds: f64,
}
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Stream {
    pub track: u64,
    pub kind: String,
    pub packets: u64,
    pub missing_timestamps: u64,
    pub first_seconds: Option<f64>,
    pub end_seconds: Option<f64>,
    pub gap_count: u64,
    pub gaps: Vec<Gap>,
}
#[derive(PartialEq)]
struct Point {
    time: f64,
    duration: f64,
}
impl Eq for Point {}
impl Ord for Point {
    fn cmp(&self, other: &Self) -> Ordering {
        self.time
            .total_cmp(&other.time)
            .then(self.duration.total_cmp(&other.duration))
    }
}
impl PartialOrd for Point {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

pub struct Timeline {
    pub stream: Stream,
    queue: BinaryHeap<Reverse<Point>>,
    max_time: f64,
    threshold: f64,
}
impl Timeline {
    pub fn new(track: u64, kind: String, threshold: f64) -> Self {
        Self {
            stream: Stream {
                track,
                kind,
                packets: 0,
                missing_timestamps: 0,
                first_seconds: None,
                end_seconds: None,
                gap_count: 0,
                gaps: vec![],
            },
            queue: BinaryHeap::new(),
            max_time: f64::NEG_INFINITY,
            threshold,
        }
    }
    pub fn push(&mut self, time: Option<f64>, duration: f64) {
        self.stream.packets += 1;
        let Some(time) = time.filter(|t| t.is_finite()) else {
            self.stream.missing_timestamps += 1;
            return;
        };
        let duration = if duration.is_finite() {
            duration.max(0.0)
        } else {
            0.0
        };
        self.max_time = self.max_time.max(time);
        self.queue.push(Reverse(Point { time, duration }));
        // Sort a bounded presentation-time window, accommodating B frames.
        while self
            .queue
            .peek()
            .is_some_and(|p| p.0.time < self.max_time - 2.0)
            || self.queue.len() > 8192
        {
            self.commit();
        }
    }
    fn commit(&mut self) {
        let point = self.queue.pop().unwrap().0;
        let s = &mut self.stream;
        if let Some(end) = s.end_seconds
            && point.time - end > self.threshold
        {
            s.gap_count += 1;
            if s.gaps.len() < 20 {
                s.gaps.push(Gap {
                    from_seconds: end,
                    to_seconds: point.time,
                });
            }
        }
        s.first_seconds = Some(s.first_seconds.map_or(point.time, |t| t.min(point.time)));
        s.end_seconds = Some(s.end_seconds.map_or(point.time + point.duration, |t| {
            t.max(point.time + point.duration)
        }));
    }
    pub fn finish(mut self) -> Stream {
        while !self.queue.is_empty() {
            self.commit();
        }
        self.stream
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn gaps_respect_frame_duration_and_reordering() {
        let mut t = Timeline::new(1, "video".into(), 0.5);
        for time in [0.0, 0.3, 0.1, 0.2, 1.0, 1.1] {
            t.push(Some(time), 0.1);
        }
        let s = t.finish();
        assert_eq!(s.gap_count, 1);
        assert!((s.gaps[0].from_seconds - 0.4).abs() < 0.0001);
        let mut t = Timeline::new(1, "video".into(), 0.5);
        t.push(Some(0.0), 5.0);
        t.push(Some(5.0), 5.0);
        assert_eq!(t.finish().gap_count, 0);
    }
    #[test]
    fn bounds_examples_and_reports_missing_timestamps() {
        let mut t = Timeline::new(1, "audio".into(), 0.5);
        for i in 0..100 {
            t.push(Some(f64::from(i) * 4.0), 0.1);
        }
        t.push(None, 0.0);
        let s = t.finish();
        assert_eq!(s.gaps.len(), 20);
        assert_eq!(s.gap_count, 99);
        assert_eq!(s.missing_timestamps, 1);
    }
}
