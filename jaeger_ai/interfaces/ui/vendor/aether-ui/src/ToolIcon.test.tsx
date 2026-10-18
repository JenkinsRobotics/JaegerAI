import { render } from "@testing-library/react";
import { expect, test } from "vitest";
import { ToolIcon, toolIconNames } from "./ToolIcon";

test("illustrated tools isolate gradient references across repeated instances", () => {
  const { container } = render(<><ToolIcon name="extrude" /><ToolIcon name="extrude" /></>);
  const ids = [...container.querySelectorAll('[id]')].map(node => node.id);
  expect(new Set(ids).size).toBe(ids.length);
  for (const svg of container.querySelectorAll('svg')) {
    expect(svg.getAttribute('aria-hidden')).toBe('true');
    for (const element of svg.querySelectorAll('[fill]')) {
      const id = element.getAttribute('fill')?.match(/^url\(#(.+)\)$/)?.[1];
      if (id) expect([...svg.querySelectorAll('[id]')].some(node => node.id === id)).toBe(true);
    }
  }
});

test("every shared illustration is scalable vector geometry with no font or raster dependency", () => {
  const { container } = render(<>{toolIconNames.map(name => <ToolIcon key={name} name={name} />)}</>);
  expect(container.querySelectorAll('svg')).toHaveLength(toolIconNames.length);
  expect(container.querySelector('text,image,script,foreignObject')).toBeNull();
  for (const svg of container.querySelectorAll('svg')) {
    expect(svg.getAttribute('viewBox')).toBe('0 0 32 32');
    expect(svg.querySelector('path,circle')).not.toBeNull();
  }
});
