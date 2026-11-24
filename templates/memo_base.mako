<%include file="about_me.mako"/>

<task>
<%block name="task"/>
</task>

<output_format>
Write markdown. Do not put it in a code block. Do not write a title: the page adds one.
<%block name="sections"/>
Length: one page, ${words} words or fewer.

Writing style:
  - Write as an investment analyst writes for a portfolio manager: specific and short, no filler.
  - Use short bullets. Nest a bullet only to add a cause or a consequence.
  - Describe prospects in plain English ("very likely", "a coin toss", "a long shot"). Do not print probabilities.
  - Give the date when you know it.
  - Link a claim to its source with an inline markdown link on 1 to 3 words of the claim.
    The source is the URL of the question, or the page that you found.

Do not:
  - Do not say that the input is from prediction markets. The reader knows.
  - Do not give general advice ("monitor closely", "review regularly", "stay diversified").
  - Do not name broad index or sector ETFs. Name the sector, the bond duration or the company.
  - Do not invent numbers, quotes or sources. If you do not know something, omit it.
  - Do not go through the questions one by one. Combine them into conclusions.
  - Do not comment on the input, its dates or its quality.
</output_format>
