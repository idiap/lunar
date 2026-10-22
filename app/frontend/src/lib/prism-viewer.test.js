// SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
//
// SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
// Neuro-symbolic AI Group
//
// SPDX-License-Identifier: Apache-2.0
import assert from 'node:assert/strict';
import test from 'node:test';
import { layoutComplexGraph } from './prism-viewer.js';

test('layout preserves source graph endpoints and adds no inferred topology', () => {
  const workflow = { source_text: '# Adaptive feedback iteration loop', graph: {
    reasoning: 'ReviewFeedbackLoop',
    nodes: [
      {id:'request',kind:'input',output_type:'Request'},
      {id:'a',kind:'occurrence',method:'Review',certificate:'Criteria'},
      {id:'b',kind:'occurrence',method:'Review'},
      {id:'c',kind:'occurrence',method:'Synthesize'},
      {id:'__result__',kind:'result',output_type:'Report'},
    ],
    edges: [
      {source:'request',target:'a',kind:'data'},
      {source:'request',target:'b',kind:'data'},
      {source:'a',target:'c',kind:'data'},
      {source:'b',target:'c',kind:'data'},
      {source:'c',target:'__result__',kind:'return'},
    ],
  }};
  const rendered = layoutComplexGraph(workflow);
  assert.deepEqual(rendered.nodes.map(n => n.id), workflow.graph.nodes.map(n => n.id));
  assert.deepEqual(rendered.edges.map(e => [e.source,e.target]), workflow.graph.edges.map(e => [e.source,e.target]));
  assert.ok(rendered.nodes.every(n => !n.data.synthetic));
  assert.deepEqual(layoutComplexGraph(workflow), rendered);
});

test('declared parallel blocks reuse module frames and sigma joins without changing edges', () => {
  const workflow = { graph: {
    nodes: [
      {id:'input',kind:'input',output_type:'Request'},
      {id:'fork',kind:'topology',label:'Parallel',topology_kind:'parallel',topology_role:'fork',members:['left','right'],join_id:'join'},
      {id:'left',kind:'occurrence',method:'ConstructCausalModel',output_type:'CausalModel'},
      {id:'right',kind:'occurrence',method:'ContrastContexts',output_type:'ContextContrast'},
      {id:'join',kind:'topology',label:'Parallel join',topology_kind:'parallel',topology_role:'join',parallel_id:'fork'},
      {id:'result',kind:'result',output_type:'Report'},
    ],
    edges: [
      {source:'input',target:'fork',kind:'control',label:'sequence'},
      {source:'fork',target:'left',kind:'control',label:'parallel'},
      {source:'fork',target:'right',kind:'control',label:'parallel'},
      {source:'left',target:'join',kind:'control',label:'join'},
      {source:'right',target:'join',kind:'control',label:'join'},
      {source:'join',target:'result',kind:'control',label:'complete'},
    ],
  }};
  const original = structuredClone(workflow);
  const rendered = layoutComplexGraph(workflow);
  const frame = rendered.nodes.find(n => n.data.role === 'module');
  assert.equal(frame.data.label, 'Convergent module 1');
  assert.deepEqual(frame.data.members, ['left','right']);
  assert.equal(rendered.nodes.find(n => n.id === 'join').data.role, 'aggregate');
  assert.equal(rendered.nodes.find(n => n.id === 'join').data.label, 'Σ');
  for (const id of frame.data.members) {
    const node = rendered.nodes.find(n => n.id === id);
    assert.ok(node.position.x > frame.position.x);
    assert.ok(node.position.y > frame.position.y);
    assert.ok(node.position.x + node.width < frame.position.x + frame.style.width);
    assert.ok(node.position.y + node.height < frame.position.y + frame.style.height);
  }
  assert.equal(rendered.edges.find(e => e.target === 'join').data.role, 'converging');
  assert.equal(rendered.edges.find(e => e.source === 'join').data.label, 'integrated signal');
  assert.deepEqual(rendered.edges.map(e => [e.source,e.target]), workflow.graph.edges.map(e => [e.source,e.target]));
  assert.deepEqual(layoutComplexGraph(workflow), rendered);
  assert.deepEqual(workflow, original);
});

test('all reasoning blocks have distinct selectable options, including duplicate names', async () => {
  const { reasoningOptions } = await import('./prism-viewer.js');
  const options = reasoningOptions({workflows:[
    {id:'first',label:'Review',source:'repository/first.prism'},
    {id:'second',label:'Review',source:'repository/second.prism'},
    {id:'third',label:'OtherReasoning',source:'repository/first.prism'},
  ]});
  assert.deepEqual(options, [
    {value:'first',label:'Review · repository/first.prism'},
    {value:'second',label:'Review · repository/second.prism'},
    {value:'third',label:'OtherReasoning'},
  ]);
});

test('executable declarations cannot masquerade as reasoning views', async () => {
  const { validatePrismBundle } = await import('./prism-viewer.js');
  assert.throws(() => validatePrismBundle({kind:'prism-viewer-bundle',schema_version:1,
    projects:[{id:'project',workflows:[{id:'execution',graph:{scope:'executable-workflow',nodes:[],edges:[]}}]}],
  }), /reasoning blocks/);
});
