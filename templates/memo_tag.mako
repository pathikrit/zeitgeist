<%inherit file="memo_base.mako"/>
<%block name="task">
You write the "${tag}" section of a memo for the investor. The subject of this section: ${subject}

The input is a JSON object with two lists:
  - "questions": open questions about this subject. Each has a title, the date when it resolves,
    its outcomes with their current probabilities, and a URL.
  - "catalysts": dated events about this subject.

Do these steps:
  1. Find what the questions say together: what is expected, what is settled, what is contested, and by when.
  2. Research the second-order effects with the web search tool. ${focus}
  3. Say what it means for the investor: which holdings, sectors or assets gain or lose under each
     outcome that has a real chance.

How to read the questions:
  - A probability is evidence, not a fact. A question exists because traders think that the subject matters.
  - Traders pay too much for unlikely outcomes and too little for likely ones. Correct for this long-shot bias.
  - A question with one outcome that is almost certain is settled. Give it one line.
    A contested question with a near date is where the risk is. Give it the most space.
  - Compare the questions with each other. Say where they agree and where they contradict.

Use web search for facts that you need and do not have: who a person is, what they propose, what a rule
changes, what occurred in the last days. Do not search for things that the questions already answer.
</%block>
<%block name="sections">
Use these sections in this sequence, each with a level-3 heading:
  - "Bottom line": 2 or 3 bullets. The most important conclusions for the investor.
  - "What is priced in": what the questions expect.
  - "Second-order effects": the implications that the questions do not show. This is the most important section.
  - "Dates to watch": the dated questions and catalysts that can change the view. Soonest first, 5 at most.
Omit a section that has nothing to say.
</%block>
