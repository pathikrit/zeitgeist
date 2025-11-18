<%include file="about_me.mako"/>

<task>
You will be provided an array of questions and probabilities from an online betting market
along with today's top news headlines and a list of upcoming catalyst events
Consolidate and summarize into a 1-pager investment guideline thesis report
The provided topics column can serve as hints to explore but think deeply about 2nd and 3rd order effects
and if any current news or upcoming events can impact these topics
Take into account the probabilities and the fact that the topic is being discussed in the first place
but also keep in mind that prediction markets often have moonshot bias i.e.
people sometime tend to overweight extreme low-probability outcomes and underweight high-probability ones
Use critical thinking and self-reflection
When appropriate or possible synthesize the betting market info with any relevant news or upcoming catalysts
</task>

<output_format>
Present in a markdown format with sections and sub-sections
Go from broad (e.g. macro) to narrow (e.g. sector) and finally individual names as top-level sections
Consolidate any important or relevant news items into simple bullets at the top in a separate news section
Consolidate all events and upcoming catalysts into a 'Upcoming Catalysts' section at the bottom
  - Skip generic things without any concrete timelines or dates
  - Sort by soonest to furthest out
  - If possible, for each catalyst mention a short phrase how it may impact me
  - Avoid general guidelines like 'watch for regulatory moves or geopolitical risks' as that is not helpful
This is intended to be consumed daily by a PM as a news memo, so just use the title: Daily Memo (${today.strftime('%d-%b-%Y')})
Things to avoid:
  - Don't mention that your input was prediction markets; the reader is aware of that
  - Avoid putting the exact probabilities from the input; just use plain English to describe the prospects
  - Avoid general guidelines like 'review this quarterly' or 'keep an eye'
  - Avoid mentioning broad ETF tickers as I can figure that out from the sector or bond duration etc.
  - Avoid any generic or broad statements; be succinct and specific.
  - No hallucinations: never fabricate nor use illustrative numbers, metrics, quotes, or sources
Writing style:
  - No fluff; get to the heart of the matter as quickly as possible
  - Be very careful to not be too verbose i.e. no essays; you'll waste time and lose attention
  - Use short bullet points; nest bullets in markdown if necessary
  - Everything you say should sound wise and should stand up to scrutiny
</output_format>
