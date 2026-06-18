export interface Point {
    x: number;
    y: number;
}

/**
 * Convert a mouse event's CSS-pixel position into the canvas's logical graph
 * coordinates.
 *
 * The canvas has a fixed internal resolution (e.g. 1200x800) but is stretched
 * by CSS to the container size, so CSS pixels must be scaled by
 * canvas.width / rect.width before inverting the draw transform
 * (pixel = offset + logical * zoom).
 */
export function clientToGraphPoint(
    client: Point,
    rect: { left: number; top: number; width: number; height: number },
    canvas: { width: number; height: number },
    offset: Point,
    zoom: number,
): Point {
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
        x: ((client.x - rect.left) * scaleX - offset.x) / zoom,
        y: ((client.y - rect.top) * scaleY - offset.y) / zoom,
    };
}
