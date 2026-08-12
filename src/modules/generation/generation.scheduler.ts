import { Injectable } from "@nestjs/common";
import { Interval } from "@nestjs/schedule";

import { GenerationWorker } from "./generation.worker";

@Injectable()
export class GenerationScheduler {
  constructor(private readonly worker: GenerationWorker) {}

  @Interval("generation-worker", 5000)
  run() {
    return this.worker.tick();
  }
}
