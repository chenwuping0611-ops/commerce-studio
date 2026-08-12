import { Injectable, MessageEvent } from "@nestjs/common";
import { Observable, Subject, finalize, interval, map, merge } from "rxjs";

@Injectable()
export class GenerationEventsService {
  private readonly subjects = new Map<string, Subject<MessageEvent>>();

  stream(taskId: string): Observable<MessageEvent> {
    let subject = this.subjects.get(taskId);
    if (!subject) {
      subject = new Subject<MessageEvent>();
      this.subjects.set(taskId, subject);
    }

    const heartbeats = interval(15000).pipe(
      map(() => ({
        type: "heartbeat",
        data: { taskId, at: new Date().toISOString() },
      })),
    );
    return merge(subject.asObservable(), heartbeats).pipe(
      finalize(() => {
        if (subject?.observers.length === 0) {
          this.subjects.delete(taskId);
          subject.complete();
        }
      }),
    );
  }

  publish(taskId: string, type: string, data: Record<string, unknown>) {
    this.subjects.get(taskId)?.next({
      type,
      data: {
        taskId,
        ...data,
      },
    });
  }
}
