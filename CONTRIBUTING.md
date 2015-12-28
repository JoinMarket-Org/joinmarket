Contributing to JoinMarket
============================

These notes took [this](https://github.com/bitcoin/bitcoin/blob/master/CONTRIBUTING.md)
as a starting point and are very much a work in progress.

We are working from [this](http://nvie.com/posts/a-successful-git-branching-model/) model, approximately. 
For a developer, it principally means basing all pull requests
off the develop branch. The code in develop is not guaranteed to be stable, of course, but
testing should occur there also.

Contributor Workflow
--------------------

To contribute a patch, the workflow is as follows:

  - Fork repository and checkout develop branch.
  - Create topic branch
  - Make commits.

TODO: list any coding conventions here.

In general [commits should be atomic](https://en.wikipedia.org/wiki/Atomic_commit#Atomic_commit_convention) and diffs should be easy to read. For this reason do not mix any formatting fixes or code moves with actual code changes.

Commit messages should be verbose by default consisting of a short subject line (50 chars max), a blank line and detailed explanatory text as separate paragraph(s); unless the title alone is self-explanatory (like "Corrected typo in main.cpp") then a single title line is sufficient. Commit messages should be helpful to people reading your code in the future, so explain the reasoning for your decisions. Further explanation [here](http://chris.beams.io/posts/git-commit/).

If a particular commit references another issue, please add the reference, for example "refs #1234", or "fixes #4321". Using "fixes or closes" keywords will cause the corresponding issue to be closed when the pull request is merged.


  - Push changes to your fork
  - Create pull request to develop branch.


If a pull request is specifically not to be considered for merging (yet) please prefix the title with [WIP].

The body of the pull request should contain enough description about what the patch does together with any justification/reasoning. You should include references to any discussions (for example other tickets or mailing list discussions).

At this stage one should expect comments and review from other contributors. You can add more commits to your pull request by committing them locally and pushing to your fork until you have satisfied all feedback. If your pull request is accepted for merging, you may be asked by a maintainer to squash and or rebase your commits before it will be merged. The length of time required for peer review is unpredictable and will vary from patch to patch.


###Peer Review

Anyone may participate in peer review which is expressed by comments in the pull request. Typically reviewers will review the code for obvious errors, as well as test out the patch set and opine on the technical merits of the patch. Project maintainers take into account the peer review when determining if there is consensus to merge a pull request (remember that discussions may have been spread out over github, mailing list and IRC discussions). The following language is used within pull-request comments:

  - ACK means "I have tested the code and I agree it should be merged";
  - NACK means "I disagree this should be merged", and must be accompanied by sound technical justification. NACKs without accompanying reasoning may be disregarded;
  - utACK means "I have not tested the code, but I have reviewed it and it looks OK, I agree it can be merged";
  - Concept ACK means "I agree in the general principle of this pull request";
  - Nit refers to trivial, often non-blocking issues.

Reviewers should include the commit hash which they reviewed in their comments.
