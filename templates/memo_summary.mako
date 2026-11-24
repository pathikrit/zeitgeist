<%inherit file="memo_base.mako"/>
<%block name="task">
You write the front page of a memo for the investor.
The input is a JSON object with one section for each of these subjects: ${', '.join(tags)}.
Analysts wrote the sections. Condense them into one page.

Do these steps:
  1. Rank by importance to the investor, not by subject. A subject with nothing important gets no space.
  2. Connect the subjects. Find where one section changes how to read a different section
     (for example, a tariff decision and an inflation report).
  3. Keep the link of each claim that you keep.

Use only what is in the sections. Do not add facts.
</%block>
<%block name="sections">
Use these sections in this sequence, each with a level-3 heading:
  - "Bottom line": 3 to 5 bullets. The conclusions that matter most across all subjects.
  - "Themes": 5 themes at most. Each theme is one bold phrase, then 1 to 3 bullets.
  - "Dates to watch": soonest first, 7 at most, each with a short phrase that says why it matters.
</%block>
