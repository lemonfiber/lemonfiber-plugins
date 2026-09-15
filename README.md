# lemonfiber-plugins

The registry: where a plugin is registered to be found.

**It is not a dependency.** Publishing a plugin needs nothing beyond a git
repository ([`F10-R9`](https://github.com/lemonfiber/spec/blob/main/10-functional/features/f-extensibility/f10-authoring.md)).
An operator installs from any git source or local path they name
([`F5-R4`](https://github.com/lemonfiber/spec/blob/main/10-functional/features/f-extensibility/f5-plugin-catalogue.md)),
technical validation is identical either way (`F5-R6`), and an installed plugin
goes on working with this repository unreachable (`F5-R10`). An author who never
registers still has a working, installable plugin. What registering adds is that
somebody read it, and that an operator can find it without being told the URL.

**It is not a mirror.** An entry records *where* a plugin is and the revision of
it that was read — never a copy. The plugin's own repository owns its manifest,
its recordings and its proofs, and a second copy here would be a second answer to
*what does this plugin declare*, with nothing to say which of the two an operator
installed. `F5-R12` refuses two plugins of the same name from different origins;
a registry of copies would manufacture that case rather than refuse it.

## What is in it

```
plugins/
└── <id>.toml      where it is, and the revision somebody read
```

An entry is six lines:

```toml
schema = 1

[plugin]
id       = "komga"
origin   = "https://github.com/lemonfiber/plugin-komga"
revision = "4c28c6216bc9063e174161bba7ea40409502a56f"
note     = "Comics are the one medium the bundled stack acquires nothing for."
```

`revision` is a full commit and never a tag or a branch, because review is of a
tree rather than of a name: a name can be repointed after it was read, which is
the whole of what registering it was for. Moving a plugin forward is a pull
request moving that one line, and that is the same person reading again.

## How to register

1. **Have a plugin that passes its own CI.** Copy
   [`plugin-template`](https://github.com/lemonfiber/plugin-template), replace
   the service, record your fixtures, and get your own repository green. Nothing
   here can be registered that would not pass there.
2. **Fork this repository and add one file**, `plugins/<your-id>.toml`, with the
   five fields above. The id is your plugin's `[plugin].id` and the file is named
   for it.
3. **Point `revision` at the commit you want read.** Not `main` — the exact
   commit.
4. **Open a pull request.** CI runs before anybody looks (below). If it is red,
   the message names what is wrong and where; fix it and push.
5. **A person reads the diff and the revision it points at**, and merges. That is
   the whole of what being in this list means, and
   [F5](https://github.com/lemonfiber/spec/blob/main/10-functional/features/f-extensibility/f5-plugin-catalogue.md)
   is careful about what it does and does not buy: a schema that was checked,
   proofs that ran, and a person who read it. It is not a reading of the image —
   a manifest is forty lines and a container image is not reviewable by anybody,
   which is why the image is pinned by digest rather than vouched for.

Updating is the same thing with one line changed. Removing a plugin is deleting
its file; nothing installed stops working, because nothing installed resolves
anything here.

## What CI checks on a registration

Three jobs, and the order is deliberate — the cheap answer about your *entry*
comes before anything is fetched, so a reviewer is never left wondering whether
the problem is the registration or the plugin.

| Job | What it decides |
| --- | --- |
| `entries` | Every entry says what an entry may say: a plugin id that matches its filename, an `https` origin with no credentials, a full commit, no field this registry does not read, and no origin registered twice under two names. Its own rules are self-tested first, so a green run is a run whose gate still refuses things. |
| `harness` | The programs under `.github/interim/` are byte-identical to `plugin-template`'s. A registry holding its own fork of the validator would be a second opinion about what a manifest means, and plugin repositories would go green against a rule this one had dropped. |
| `plugins` | Each registered revision is fetched, and out of the data in it: the manifest is validated against the schema lemonfiber publishes, every claim and contribution is held to the published capability vocabulary and extension points, every declared reach is checked statically, and every declared proof is run against that plugin's own recorded responses. |

Those checks are `REPO-R61`, and they run against the `lemonfiber` release named
in [`targets.toml`](targets.toml) (`REPO-R56`) — a catalogue that validated
against a different build than the operator runs would be vouching for something
it had not tested.

**Nothing from a registered repository is executed** (`REPO-R62`). The manifest,
the recordings and `targets.toml` are copied out of the fetched tree and
everything else is left where it lies; the programs that read them are this
repository's own. That is the same line
[`F3-R6`](https://github.com/lemonfiber/spec/blob/main/10-functional/features/f-extensibility/f3-stack-manifests.md)
draws on an operator's machine, for the same reason: a catalogue that ran a
stranger's script in order to decide whether the stranger's data was acceptable
would be answering the question by doing the thing the question is about.

The proofs run against recordings rather than against a live service
(`F10-R4`) and are reported as what they are (`F10-R6`) — a claim about what a
plugin declares, which is weaker than a claim about a service that answered.

Run any of it yourself:

```sh
python3 registry/entry.py --self-test   # the gate refuses what it should
python3 registry/entry.py               # every entry, read
python3 registry/check.py               # every registration, held to everything
python3 registry/check.py --only komga  # one of them
```

`check.py` needs `git`, a GitHub token in the environment, and `jsonschema`.

## Why `plugin-template` is not registered here

It is the repository an author copies, and what it installs — Kavita — is there
so that its proofs are proofs rather than because anybody should run it. Putting
it in a list an operator browses for something to install would be offering a
teaching artefact as a thing to use.

It is held to the format all the same, and somewhere better suited to it: the
spec's [`70-operations/plugins.toml`](https://github.com/lemonfiber/spec/blob/main/70-operations/plugins.toml)
registers it for the release train, so a release that breaks what every author
starts from stops the train. That is a different question from *what may I
install*, and it belongs to a different list.

## What this never becomes

**Not a runtime dependency** (`REPO-R58`). Nothing published here is resolved by
an installed plugin while it runs. The moment it were, every operator's stack
would depend on this repository being reachable.

**Not a service** (`REPO-R59`). No backend, no database, no state beyond the
repository. A catalogue that needed operating would be a second product, and it
would be one this project has said it does not build.

**Not a walled garden.** The curated lane is not the only road, and lemonfiber
says plainly which one an operator is on: a plugin installed from anywhere else
is installed as unreviewed, said so at install time, and carries that for as long
as it is installed (`F5-R5`). The honest limit of this list is that the reviewer
is one person — which is exactly why `F5-R4` keeps an operator's own source on
the same technical terms.

## Licence

The registry data in this repository is under the Hippocratic License 3.0
(HL3-CORE) — see [LICENSE](LICENSE). Each registered plugin carries its own
licence in its own repository, and `license` in a plugin's manifest is a fact
about the upstream service it configures rather than about anything here.
