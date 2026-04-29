/**
 * Minimal hex-axes radar component for the analysis page.
 *
 * This is a simplified port of frontend/src/components/hex/Hex.tsx —
 * just enough to render 6 axes (Pulse, Quality, Risk, etc) with values
 * 0..1. The web version has axis labels, gradients, and animations; we
 * skip those for Phase 0 and add them in Phase 2.
 */

import Svg, { Polygon, Line, Circle, Text as SvgText } from 'react-native-svg';
import { View } from 'react-native';

interface Props {
  axes: Record<string, number>; // axisName -> value 0..1
  size?: number;
  fill: string;
  stroke: string;
  axisColor: string;
  labelColor: string;
}

export function HexAxes({
  axes,
  size = 240,
  fill,
  stroke,
  axisColor,
  labelColor,
}: Props) {
  const cx = size / 2;
  const cy = size / 2;
  const r = size / 2 - 24; // padding for labels
  const names = Object.keys(axes);
  const n = Math.max(names.length, 3);

  // Vertices for the value polygon and axis spokes.
  const angle = (i: number) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const point = (i: number, mag: number) => {
    const a = angle(i);
    return {
      x: cx + Math.cos(a) * r * mag,
      y: cy + Math.sin(a) * r * mag,
    };
  };

  const valuePoints = names
    .map((name, i) => {
      const v = clamp01(axes[name]);
      const p = point(i, v);
      return `${p.x},${p.y}`;
    })
    .join(' ');

  return (
    <View>
      <Svg width={size} height={size}>
        {/* Outer ring */}
        <Circle cx={cx} cy={cy} r={r} stroke={axisColor} strokeWidth={1} fill="none" />
        {/* Spokes + labels */}
        {names.map((name, i) => {
          const tip = point(i, 1);
          const label = point(i, 1.12);
          return (
            <Line
              key={`spoke-${name}`}
              x1={cx}
              y1={cy}
              x2={tip.x}
              y2={tip.y}
              stroke={axisColor}
              strokeWidth={1}
            />
          );
        })}
        {/* Value polygon */}
        <Polygon
          points={valuePoints}
          fill={fill}
          fillOpacity={0.35}
          stroke={stroke}
          strokeWidth={2}
        />
        {/* Labels */}
        {names.map((name, i) => {
          const p = point(i, 1.12);
          return (
            <SvgText
              key={`label-${name}`}
              x={p.x}
              y={p.y}
              fontSize={10}
              fill={labelColor}
              textAnchor="middle"
            >
              {name}
            </SvgText>
          );
        })}
      </Svg>
    </View>
  );
}

function clamp01(v: number | undefined | null): number {
  if (v == null || !Number.isFinite(v)) return 0;
  return Math.max(0, Math.min(1, v));
}
