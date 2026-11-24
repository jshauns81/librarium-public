import { expect, test } from "vitest";
import { contrast, lightFromPixels } from "../src/reading";

const channels = (value: string) => value.split(" ").map(Number);
const solid = (r: number, g: number, b: number, count = 64) =>
  new Uint8ClampedArray(
    Array.from({ length: count }, () => [r, g, b, 255]).flat(),
  );

test("pale room text reads at 5:1 on every deep room, whatever the cover", () => {
  for (const [r, g, b] of [
    [240, 220, 40],
    [60, 200, 90],
    [90, 200, 230],
    [200, 40, 40],
    [150, 60, 200],
  ]) {
    const light = lightFromPixels(solid(r, g, b))!;
    expect(
      contrast([0xe7, 0xdc, 0xcf], channels(light.deep)),
    ).toBeGreaterThanOrEqual(5);
    // The dark room's rubric reads on the room too.
    expect(
      contrast([0xef, 0x92, 0x70], channels(light.deep)),
    ).toBeGreaterThanOrEqual(4.6);
  }
});

test("light rooms take the same hue, pale", () => {
  const light = lightFromPixels(solid(200, 40, 40))!;
  const [r, g, b] = channels(light.light);
  expect(r).toBeGreaterThan(g);
  expect(Math.min(r, g, b)).toBeGreaterThan(180);
});

test("a cover with no readable colour gives no light", () => {
  expect(lightFromPixels(solid(0, 0, 0))).toBeNull();
});
