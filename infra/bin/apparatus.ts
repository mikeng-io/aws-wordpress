#!/usr/bin/env node
/**
 * CDK app for the study's apparatus.
 *
 * There is deliberately no "platform" stack here.  Stacks are added per experiment,
 * built to answer one question, and are allowed to be thrown away afterwards.
 * Resist generalising across experiments until at least three of them exist and
 * the shared shape is observed rather than guessed.
 */
import { App } from 'aws-cdk-lib';

const app = new App();

// Experiment stacks are registered here as they are specced.
//
//   E1 - mount topology        (does ECS on EC2 mount EFS per host or per task?)
//   E2 - placement differential (N tasks on 1 host vs N hosts, identical EFS)
//   E3 - Fargate ephemeral storage latency
//
// E0 needs no AWS resources; it runs locally under experiments/E0-syscall-census.

app.synth();
