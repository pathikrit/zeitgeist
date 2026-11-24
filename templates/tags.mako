<%page args="item"/>\
<tags>
Each ${item} gets one tag. These are the tags and their subjects:
% for tag, subject in tags.items():
  - "${tag}": ${subject}
% endfor

Obey these rules when you select the tag:
  - Find the most important subject of the ${item}. This is the thing that the ${item} measures or announces.
  - Select the tag for that subject. Do not select the tag for the cause of the event.
    Example: the price of crude oil during a war gets the tag "Commodities".
  - If two tags apply equally, select the tag that comes first in the list.
  - Select "Other" only if no other tag applies.
</tags>
