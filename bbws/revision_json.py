# -*- coding: utf8 -*-

# Copyright (C) 2014-2015  Ben Ockmore

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

from bbschema import (Alias, Annotation,  Disambiguation, Entity,
                      EntityRevision, CreatorData, PublicationData, EditionData,
                      PublisherData, WorkData, Relationship, RelationshipEntity,
                      RelationshipText, RelationshipTree)
from sqlalchemy.orm.exc import NoResultFound

from . import db


class JSONParseError(Exception):
    pass


def create_entity(revision_json):
    # Make an entity
    entity = Entity()

    # Create the correct type of data
    if 'publication_data' in revision_json:
        entity_data = PublicationData(**revision_json['publication_data'])
    elif 'creator_data' in revision_json:
        entity_data = CreatorData(**revision_json['creator_data'])
    elif 'edition_data' in revision_json:
        entity_data = EditionData(**revision_json['edition_data'])
    elif 'publisher_data' in revision_json:
        entity_data = PublisherData(**revision_json['publisher_data'])
    elif 'work_data' in revision_json:
        entity_data = WorkData(**revision_json['work_data'])
    else:
        raise JSONParseError('Unrecognized entity type!')

    # Create any specified aliases, annotations or disambiguations
    if 'annotation' in revision_json:
        annotation = Annotation(content=revision_json['annotation'])
        entity_data.annotation = annotation

    if 'disambiguation' in revision_json:
        disambiguation = Disambiguation(
            comment=revision_json['disambiguation']
        )
        entity_data.disambiguation = disambiguation

    if 'aliases' in revision_json:
        for alias_json in revision_json['aliases']:
            alias = Alias(
                name=alias_json['name'], sort_name=alias_json['sort_name'],
                language_id=alias_json['language_id'],
                primary=alias_json['primary'],
            )

            if alias_json['default'] and (entity_data.default_alias is None):
                entity_data.default_alias = alias

            entity_data.aliases.append(alias)

    return (entity, entity_data)


def update_aliases(entity_data, alias_json):
    # Aliases will be a list of:
    # [id, {name:'', sort_name:'', language_id:''}]
    # If id is null, add, if second object is null, delete,
    # otherwise, update.

    ids = [x for x, _ in alias_json if x is not None]

    # This removes all entries where id is not None (updated + deleted)
    aliases = [alias for alias in entity_data.aliases
               if alias.alias_id not in ids]

    new_default = None

    # Then re-add them, with modified properties (updated + new)
    for alias_id, alias_props in alias_json:
        if alias_props is not None:
            if alias_id is None:
                # Create new alias
                new_alias = Alias(
                    name=alias_props['name'],
                    sort_name=alias_props['sort_name'],
                    language_id=alias_props['language_id'],
                    primary=alias_props['primary']
                )

                if ((alias_props.get('default', None) is not None) and
                        (new_default is None)):
                    new_default = new_alias
            else:
                # Copy existing alias, and modify
                qry = db.session.query(Alias).filter_by(alias_id=alias_id)
                try:
                    existing = qry.one()
                except NoResultFound:
                    # Ignore the error, and move to the next id.
                    continue
                new_alias = Alias.copy(existing)
                for attr, val in alias_props.items():
                    if attr != 'alias_id':
                        setattr(new_alias, attr, val)

                if ((alias_props.get('default', None) is not None) and
                        (new_default is None)):
                    new_default = new_alias

            aliases.append(new_alias)

    # Now, unset the default alias if it was deleted
    if entity_data.default_alias not in aliases:
        entity_data.default_alias = None

    # And set it to the new default is the default isn't already set
    if entity_data.default_alias is None:
        entity_data.default_alias = new_default

    return aliases


def update_entity(revision_json):
    try:
        entity = db.session.query(Entity).filter_by(
            entity_gid=revision_json['entity_gid'][0]
        ).one()
    except NoResultFound:
        return (None, None)

    entity_data = entity.master_revision.entity_data

    annotation = entity_data.annotation
    disambiguation = entity_data.disambiguation

    # TODO: Refactor this in some nice OO way.
    data_key = None
    if 'publication_data' in revision_json:
        entity_data = PublicationData.copy(entity_data)
        data_key = 'publication_data'
    elif 'creator_data' in revision_json:
        entity_data = CreatorData.copy(entity_data)
        data_key = 'creator_data'
    elif 'edition_data' in revision_json:
        entity_data = EditionData.copy(entity_data)
        data_key = 'edition_data'
    elif 'publisher_data' in revision_json:
        entity_data = PublisherData.copy(entity_data)
        data_key = 'publisher_data'
    elif 'work_data' in revision_json:
        entity_data = WorkData.copy(entity_data)
        data_key = 'work_data'

    if data_key is not None:
        for attr, val in revision_json[data_key].items():
            if attr != 'entity_data_id':
                setattr(entity_data, attr, val)

    if 'annotation' in revision_json:
        annotation = Annotation(
            content=revision_json['annotation']
        )

    if 'disambiguation' in revision_json:
        # Create new disambiguation object
        disambiguation = Disambiguation(
            comment=revision_json['disambiguation']
        )

    if 'aliases' in revision_json:
        aliases = update_aliases(entity_data, revision_json['aliases'])
    else:
        aliases = entity_data.aliases

    entity_changed = (
        (disambiguation is not None and
            disambiguation.disambiguation_id is None) or
        (annotation is not None and annotation.annotation_id is None) or
        (entity_data.entity_data_id is None) or (aliases != entity_data.aliases)
    )

    if entity_changed:
        new_data = entity_data
        new_data.aliases = aliases
        new_data.annotation = annotation
        new_data.disambiguation = disambiguation

        return (entity, new_data)

    return (entity, entity_data)


def merge_entity(revision_json):
    pass


def delete_entity(revision_json):
    pass


def create_relationship(revision_json):
    relationship = Relationship()

    tree = RelationshipTree()
    tree.relationship_type_id = revision_json['relationship_type_id']

    for entity in revision_json.get('entities', []):
        rel_entity = RelationshipEntity(entity_gid=entity['gid'],
                                        position=entity['position'])
        tree.entities.append(rel_entity)

    for text in revision_json.get('text', []):
        rel_text = RelationshipText(text=text['text'],
                                    position=text['position'])
        tree.text.append(rel_text)

    return (relationship, tree)


def update_relationship(revision_json):
    pass


def delete_relationship(revision_json):
    pass


def parse_changes(revision_json):
    """Parses the recieved JSON and attempts to create a new revision using the
    specified changes.
    """

    # First, determine which type of edit this is.
    if 'entity_gid' in revision_json:
        entity_gid = revision_json['entity_gid']
        if not entity_gid:
            # If entity_gid is empty, then this is a CREATE.
            return create_entity(revision_json)
        elif len(entity_gid) == 1:
            # If there is 1 element in entity_gid, attempt an update.
            return update_entity(revision_json)
        elif entity_gid[-1] is None:
            # If entity_gid[-1] is None, then this is a deletion.
            return delete_entity(revision_json)
        else:
            # If entity_gid[-1] is not None, then this is a merge.
            return merge_entity(revision_json)
    elif 'relationship_id' in revision_json:
        relationship_id = revision_json['relationship_id']
        if not relationship_id:
            # If relationship_id is empty, then CREATE a new relationship.
            return create_relationship(revision_json)
        elif relationship_id[-1] is None:
            # Delete the relationship
            delete_relationship(revision_json)
        else:
            # Update the relationship
            update_relationship(revision_json)


def format_changes(base_revision_id, new_revision_id):
    """This analyzes the changes from one revision to another, and formats
    them into a single JSON structure for serving through the webservice.
    """

    # This may throw a "NoResultsFound" exception.
    new_revision = \
        db.session.query(EntityRevision).\
        filter_by(revision_id=new_revision_id).one()

    new_data = new_revision.entity_data
    new_annotation = (new_data.annotation.content
                      if new_data.annotation is not None else None)
    new_disambiguation = (new_data.disambiguation.comment
                          if new_data.disambiguation is not None else None)
    new_aliases = new_data.aliases

    if base_revision_id is None:
        base_data = None
        base_annotation = None
        base_disambiguation = None
        base_aliases = None
    else:
        base_revision = db.session.query(EntityRevision).filter_by(
            revision_id=base_revision_id
        ).one()
        base_data = base_revision.entity_data

        base_annotation = (base_data.annotation.content
                           if base_data.annotation is not None else None)
        base_disambiguation = (
            base_data.disambiguation.comment
            if base_data.disambiguation is not None else None
        )
        base_aliases = base_data.aliases

    return {
        'data': [base_data, new_data],
        'annotation': [base_annotation, new_annotation],
        'disambiguation': [base_disambiguation, new_disambiguation],
        'aliases': [base_aliases, new_aliases]
    }
