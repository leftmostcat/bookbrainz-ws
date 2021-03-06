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


from flask import request
from flask.ext.restful import Resource, abort, marshal, reqparse

from bbschema import EditorStats, Message, MessageReceipt, User, UserType
from sqlalchemy.orm.exc import NoResultFound

from . import db, oauth_provider, structures


class UserResource(Resource):
    """ A Resource representing a User of the webservice. """
    def get(self, user_id):
        try:
            user = db.session.query(User).filter_by(user_id=user_id).one()
        except NoResultFound:
            abort(404)

        return marshal(user, structures.user)


class UserStatsResource(Resource):
    """ A Resource providing statistics about a User of the webservice. """

    def get(self, user_id):
        try:
            stats = db.session.query(EditorStats).\
                filter_by(user_id=user_id).one()
        except NoResultFound:
            abort(404)

        return marshal(stats, structures.editor_stats)


class UserSecretsResource(Resource):
    """ Provides the user's own secrets for authenticated users. """

    @oauth_provider.require_oauth()
    def get(self):
        return marshal(request.oauth.user, structures.user_secrets)


class UserResourceList(Resource):
    """ A Resource representing a list of Users of the webservice. """

    get_parser = reqparse.RequestParser()
    get_parser.add_argument('limit', type=int, default=20)
    get_parser.add_argument('offset', type=int, default=0)

    def get(self):
        args = self.get_parser.parse_args()
        query = db.session.query(User).offset(args.offset).limit(args.limit)
        users = query.all()

        return marshal({
            'offset': args.offset,
            'count': len(users),
            'objects': users
        }, structures.user_list)

    post_parser = reqparse.RequestParser()
    post_parser.add_argument('name', type=unicode, required=True)
    post_parser.add_argument('email', type=unicode, required=True)
    post_parser.add_argument('user_type_id', type=unicode, required=True)

    def post(self):
        args = self.post_parser.parse_args()
        user = User(name=args.name, email=args.email,
                    user_type_id=args.user_type_id)
        db.session.add(user)
        db.session.commit()

        return marshal(user, structures.user)


class UserTypeResourceList(Resource):
    def get(self):
        types = db.session.query(UserType).all()
        return marshal({
            'objects': types
        }, structures.user_type_list)


class UserMessageResource(Resource):

    @oauth_provider.require_oauth()
    def get(self, message_id):
        try:
            message = db.session.query(Message).\
                filter_by(message_id=message_id).one()
        except NoResultFound:
            abort(404)

        # We have a message - check that the user should see it
        for receipt in message.receipts:
            if receipt.recipient_id == request.oauth.user.user_id:
                message.receipt = receipt
                data = marshal(message, structures.message)
                # For now, archive the message once GET has run once
                message.receipt.archived = True
                db.session.commit()
                return data

        if message.sender_id == request.oauth.user.user_id:
            return marshal(message, structures.message)

        abort(401)  # Unauthorized


class UserMessageInboxResource(Resource):

    get_parser = reqparse.RequestParser()
    get_parser.add_argument('limit', type=int, default=20)
    get_parser.add_argument('offset', type=int, default=0)

    @oauth_provider.require_oauth()
    def get(self):
        args = self.get_parser.parse_args()
        messages = db.session.query(Message).join(MessageReceipt).\
            filter(MessageReceipt.recipient_id == request.oauth.user.user_id).\
            filter(MessageReceipt.archived == False).\
            offset(args.offset).limit(args.limit).all()

        return marshal({
            'offset': args.offset,
            'count': len(messages),
            'objects': messages
        }, structures.message_list)


class UserMessageArchiveResource(Resource):

    get_parser = reqparse.RequestParser()
    get_parser.add_argument('limit', type=int, default=20)
    get_parser.add_argument('offset', type=int, default=0)

    @oauth_provider.require_oauth()
    def get(self):
        args = self.get_parser.parse_args()
        messages = db.session.query(Message).join(MessageReceipt).\
            filter(MessageReceipt.recipient_id == request.oauth.user.user_id).\
            filter(MessageReceipt.archived == True).\
            offset(args.offset).limit(args.limit).all()

        return marshal({
            'offset': args.offset,
            'count': len(messages),
            'objects': messages
        }, structures.message_list)


class UserMessageSentResource(Resource):

    get_parser = reqparse.RequestParser()
    get_parser.add_argument('limit', type=int, default=20)
    get_parser.add_argument('offset', type=int, default=0)

    @oauth_provider.require_oauth()
    def get(self):
        args = self.get_parser.parse_args()
        messages = db.session.query(Message).\
            filter(Message.sender_id == request.oauth.user.user_id).\
            offset(args.offset).limit(args.limit).all()

        return marshal({
            'offset': args.offset,
            'count': len(messages),
            'objects': messages
        }, structures.message_list)

    post_parser = reqparse.RequestParser()
    post_parser.add_argument('recipient_ids', type=int, action='append',
                             required=True)
    post_parser.add_argument('subject', type=unicode, required=True)
    post_parser.add_argument('content', type=unicode, required=True)

    @oauth_provider.require_oauth()
    def post(self):
        """ Add a new message to the sent messages list, to the recipients
        indicated in the POST body.
        """
        args = self.post_parser.parse_args()

        new_message = Message(sender_id=request.oauth.user.user_id,
                              subject=args.subject, content=args.content)

        recipients = []
        try:
            for recipient_id in args.recipient_ids:
                recipients.append(db.session.query(User).
                                  filter_by(user_id=recipient_id).one())
        except NoResultFound:
            abort(404)

        for recipient in recipients:
            receipt = MessageReceipt()
            receipt.recipient = recipient
            new_message.receipts.append(receipt)

        db.session.add(new_message)
        db.session.commit()

        return marshal(new_message, structures.message)


def create_views(api):
    """ Create the views relating to Users, on the Restful API. """

    api.add_resource(UserResource, '/user/<int:user_id>',
                     endpoint='user_get_single')
    api.add_resource(UserSecretsResource, '/user/secrets',
                     endpoint='user_get_secrets')
    api.add_resource(UserStatsResource, '/user/<int:user_id>/stats',
                     endpoint='editor_stats')
    api.add_resource(UserTypeResourceList, '/userType')
    api.add_resource(UserResourceList, '/user', endpoint='user_get_many')

    api.add_resource(UserMessageResource, '/message/<int:message_id>')
    api.add_resource(UserMessageInboxResource, '/message/inbox')
    api.add_resource(UserMessageArchiveResource, '/message/archive')
    api.add_resource(UserMessageSentResource, '/message/sent')
