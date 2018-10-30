Thank you for contributing to Pipenv!


### The issue

What is the thing you want to fix? Is it associated with an issue on GitHub? Please mention it.

Always consider opening an issue first to describe your problem, so we can discuss what is the best way to amend it.  Note that if you do not describe the goal of this change or link to a related issue, the maintainers may close the PR without further review.

If your pull request makes a non-insignificant change to Pipenv, such as the user interface or intended functionality, please file a PEEP. 

    https://github.com/pypa/pipenv/blob/master/peeps/PEEP-000.md

### The fix

How does this pull request fix your problem? Did you consider any alternatives? Why is this the *best* solution, in your opinion?


### The checklist

* [ ] Associated issue
* [ ] A news fragment in the `news/` directory to describe this fix with the extension `.bugfix`, `.feature`, `.behavior`, `.doc`. `.vendor`. or `.trivial` (this will appear in the release changelog). Use semantic line breaks and name the file after the issue number or the PR #.

<!--
### If this is a patch to the `vendor` directory…

Please try to refrain from submitting patches directly to `vendor` or `patched`, but raise your issue to the upstream project instead, and inform Pipenv to upgrade when the upstream project accepts the fix.

A pull request to upgrade vendor packages is strongly discouraged, unless there is a very good reason (e.g. you need to test Pipenv’s integration to a new vendor feature). Pipenv audits and performs vendor upgrades regularly, generally before a new release is about to drop.

If your patch is not or cannot be accepted by upstream, but is essential to Pipenv (make sure to discuss this with maintainers!), please remember to attach a patch file in `tasks/vendoring/patched`, so this divergence from upstream can be recorded and replayed afterwards.
-->
