You are given the following markdown memo generated from various sources like prediction markets, news, FRED data points, catalysts etc:

```md
${memo}
```

Your goal is add citations to EXISTING phrases in the above memo from the provided list of titles and urls.
Use your best guess to appropriately insert the citations as markdown inline urls when appropriate into the original markdown document
to hyperlink to relevant sources of information based on the given list of titles
DO NOT MODIFY the text of the markdown (besides adding the citations where appropriate)
DO NOT ADD new text for the link i.e. you should only hyperlink an existing phrase or number etc
i.e. your ONLY additions to the input text of the form "word1 word2 word3 word4" should be "word1 [word2 word3](url) word4"
Note how I DID NOT CHANGE the original word1 word2 etc and how DID NOT ADD any new words and nor did I delete any text from the input
I just inserted in the citation in a SHORT subsection of the input using [relevant phrase](url) markdown syntax
DO NOT ADD link for a whole sentence - your citation should be for 1-3 word phrases or key numbers only
Return JUST the original markdown (with citations) and say nothing else
Make sure to return without the leading and ending backticks i.e. the output should just be the valid markdown WITHOUT any enclosing backticks
