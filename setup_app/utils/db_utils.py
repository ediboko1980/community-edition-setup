import json
import ldap3

from setup_app import static
from setup_app.config import Config
from setup_app.static import InstallTypes, BackendTypes
from setup_app.utils import base
from setup_app.utils.cbm import CBM
from setup_app.utils import ldif_utils
from setup_app.utils.attributes import attribDataTypes
 


class DBUtils:

    processedKeys = []

    def bind(self, ldap_hostname=None, port=None, ldap_binddn=None, ldapPass=None, use_ssl=True):

        if Config.mappingLocations['default'] == 'ldap':
            self.moddb = BackendTypes.LDAP
        else:
            self.moddb = BackendTypes.COUCHBASE

        if Config.wrends_install and not (hasattr(self, 'ldap_conn')  and self.ldap_conn.bound):

            if not ldap_hostname:
                ldap_hostname = Config.ldap_hostname

            if not port:
                port = int(Config.ldaps_port)

            if not ldap_binddn:
                ldap_binddn = Config.ldap_binddn
            
            if not ldapPass:
                ldapPass = Config.ldapPass

            ldap_server = ldap3.Server(ldap_hostname, port=port, use_ssl=use_ssl)
            self.ldap_conn = ldap3.Connection(
                        ldap_server,
                        user=ldap_binddn,
                        password=ldapPass,
                        )
            base.logIt("Making LDAP Connection to host {}:{} with user {}".format(ldap_hostname, port, ldap_binddn))
            self.ldap_conn.bind()

        self.cbm = CBM(Config.couchbase_hostname, Config.couchebaseClusterAdmin, Config.cb_password)
        self.default_bucket = Config.couchbase_bucket_prefix


    def get_oxAuthConfDynamic(self):
        if self.moddb == BackendTypes.LDAP:
            self.ldap_conn.search(
                        search_base='o=gluu', 
                        search_scope=ldap3.SUBTREE,
                        search_filter='(objectClass=oxAuthConfiguration)',
                        attributes=["oxAuthConfDynamic"]
                        )

            dn = self.ldap_conn.response[0]['dn']
            oxAuthConfDynamic = json.loads(self.ldap_conn.response[0]['attributes']['oxAuthConfDynamic'][0])
        elif self.moddb == BackendTypes.COUCHBASE:
            n1ql = 'SELECT * FROM `{}` USE KEYS "configuration_oxauth"'.format(self.default_bucket)
            result = cbm.exec_query(n1ql)
            js = result.json()
            dn = js['results'][0][self.default_bucket]['dn']
            oxAuthConfDynamic = js['results'][0][self.default_bucket]['oxAuthConfDynamic']

        return dn, oxAuthConfDynamic


    def get_oxTrustConfApplication(self):
        if self.moddb == BackendTypes.LDAP:
            self.ldap_conn.search(
                        search_base='o=gluu',
                        search_scope=ldap3.SUBTREE,
                        search_filter='(objectClass=oxTrustConfiguration)',
                        attributes=['oxTrustConfApplication']
                        )
            dn = self.ldap_conn.response[0]['dn']
            oxTrustConfApplication = json.loads(self.ldap_conn.response[0]['attributes']['oxTrustConfApplication'][0])
        elif self.moddb == BackendTypes.COUCHBASE:
            n1ql = 'SELECT * FROM `{}` USE KEYS "configuration_oxtrust"'.format(self.default_bucket)
            result = self.cbm.exec_query(n1ql)
            js = result.json()
            dn = js['results'][0][self.default_bucket]['dn']
            oxAuthConfDynamic = js['results'][0][self.default_bucket]['oxTrustConfApplication']

        return dn, oxTrustConfApplication


    def set_oxAuthConfDynamic(self, entries):
        if self.moddb == BackendTypes.LDAP:
            dn, oxAuthConfDynamic = self.get_oxAuthConfDynamic()
            oxAuthConfDynamic.update(entries)

            self.ldap_conn.modify(
                    dn,
                    {"oxAuthConfDynamic": [ldap3.MODIFY_REPLACE, json.dumps(oxAuthConfDynamic, indent=2)]}
                    )
        elif self.moddb == BackendTypes.COUCHBASE:
            for k in entries:
                n1ql = 'UPDATE `{}` USE KEYS "configuration_oxauth" SET {}={}'.format(self.default_bucket, k, entries[k])
                self.cbm.exec_query(n1ql)


    def set_oxTrustConfApplication(self, entries):
        dn, oxTrustConfApplication = self.get_oxTrustConfApplication()
        oxTrustConfApplication.update(entries)

        if self.moddb == BackendTypes.LDAP:
            self.ldap_conn.modify(
                    dn,
                    {"oxTrustConfApplication": [ldap3.MODIFY_REPLACE, json.dumps(oxTrustConfApplication, indent=2)]}
                    )
        elif self.moddb == BackendTypes.COUCHBASE:
            for k in entries:
                n1ql = 'UPDATE `{}` USE KEYS "configuration_oxtrust" SET {}={}'.format(self.default_bucket, k, entries[k])
                self.cbm.exec_query(n1ql)

    def enable_script(self, inum):
        if self.moddb == BackendTypes.LDAP:
            self.ldap_conn.modify(
                    'inum={},ou=scripts,o=gluu'.format(inum),
                    {"oxEnabled": [ldap3.MODIFY_REPLACE, 'true']}
                    )
        elif self.moddb == BackendTypes.COUCHBASE:
            n1ql = 'UPDATE `{}` USE KEYS "scripts_{}" SET oxEnabled=true'.format(self.default_bucket, inum)
            self.cbm.exec_query(n1ql)

    def enable_service(self, service):
        if self.moddb == BackendTypes.LDAP:
            self.ldap_conn.modify(
                'ou=configuration,o=gluu',
                {service: [ldap3.MODIFY_REPLACE, 'true']}
                )
        elif self.moddb == BackendTypes.COUCHBASE:
            n1ql = 'UPDATE `{}` USE KEYS "configuration" SET {}=true'.format(self.default_bucket, service)
            self.cbm.exec_query(n1ql)
        
    def set_configuration(self, component, value):
        
        if self.moddb == BackendTypes.LDAP:
            self.ldap_conn.modify(
                'ou=configuration,o=gluu',
                {component: [ldap3.MODIFY_REPLACE, value]}
                )

        elif self.moddb == BackendTypes.COUCHBASE:
            n1ql = 'UPDATE `{}` USE KEYS "configuration" SET {}={}'.format(self.default_bucket, component, value)
            self.cbm.exec_query(n1ql)


    def dn_exists(self, dn):
        base.logIt("Querying LDAP for dn {}".format(dn))
        return self.ldap_conn.search(search_base=dn, search_filter='(objectClass=*)', search_scope=ldap3.BASE, attributes=['*'])

    def search(self, search_base, search_filter, search_scope=ldap3.LEVEL):
        return self.ldap_conn.search(search_base=search_base, search_filter=search_filter, search_scope=search_scope, attributes=['*'])


    def add2strlist(self, client_id, strlist):
        value2 = strlist.split(',')
        value2 = [v.strip() for v in value2]
        value2.append(client_id)
        return  ', '.join(value2)
    
    def add_client2script(self, script_inum, client_id):
        dn = 'inum={},ou=scripts,o=gluu'.format(script_inum)

        backend_location = self.get_backend_location_for_dn(dn)

        if backend_location == BackendTypes.LDAP:
            if self.dn_exists(dn):
                for e in self.ldap_conn.response[0]['attributes'].get('oxConfigurationProperty', []):
                    try:
                        oxConfigurationProperty = json.loads(e)
                    except:
                        continue
                    if isinstance(oxConfigurationProperty, dict) and oxConfigurationProperty.get('value1') == 'allowed_clients':
                        if not client_id in oxConfigurationProperty['value2']:
                            oxConfigurationProperty['value2'] = self.add2strlist(client_id, oxConfigurationProperty['value2'])
                            oxConfigurationProperty_js = json.dumps(oxConfigurationProperty)
                            self.ldap_conn.modify(
                                dn,
                                {'oxConfigurationProperty': [ldap3.MODIFY_DELETE, e]}
                                )
                            self.ldap_conn.modify(
                                dn,
                                {'oxConfigurationProperty': [ldap3.MODIFY_ADD, oxConfigurationProperty_js]}
                                )
        elif backend_location == BackendTypes.COUCHBASE:
            bucket = self.get_bucket_for_dn(dn)
            n1ql = 'SELECT oxConfigurationProperty FROM `{}` USE KEYS "scripts_{}"'.format(bucket, script_inum)
            result = self.cbm.exec_query(n1ql)
            js = result.json()

            oxConfigurationProperties = js['results'][0]['oxConfigurationProperty']
            for oxconfigprop in oxConfigurationProperties:
                if oxconfigprop.get('value1') == 'allowed_clients' and not client_id in oxconfigprop['value2']:
                    oxconfigprop['value2'] = self.add2strlist(client_id, oxconfigprop['value2'])
                    n1ql = 'UPDATE `{}` USE KEYS "scripts_{}" SET oxConfigurationProperty={}'.format(bucket, script_inum, oxConfigurationProperties)
                    self.cbm.exec_query(n1ql)
                    break

    def get_key_prefix(self, key):
        n = key.find('_')
        return key[:n+1]

    def check_attribute_exists(self, key, attribute):
        bucket = self.get_bucket_for_key(key)
        n1ql = 'SELECT `{}` FROM `{}` USE KEYS "{}"'.format(attribute, bucket, key)
        result = self.cbm.exec_query(n1ql)
        if result.ok:
            data = result.json()
            r = data.get('results', [])
            if r and r[0].get(attribute):
                return r[0][attribute]
            
    def import_ldif(self, ldif_files, bucket=None):

        for ldif_fn in ldif_files:
            parser = ldif_utils.myLdifParser(ldif_fn)
            parser.parse()

            for dn, entry in parser.entries:
                backend_location = self.get_backend_location_for_dn(dn)
                if backend_location == BackendTypes.LDAP:
                    if not self.dn_exists(dn):
                        base.logIt("Adding LDAP dn:{} entry:{}".format(dn, dict(entry)))
                        self.ldap_conn.add(dn, attributes=entry)

                elif backend_location == BackendTypes.COUCHBASE:
                    if len(entry) < 3:
                        continue
                    key, document = ldif_utils.get_document_from_entry(dn, entry)
                    cur_bucket = bucket if bucket else self.get_bucket_for_dn(dn)
                    base.logIt("Addnig document {} to Couchebase bucket {}".format(key, cur_bucket))

                    n1ql_list = []

                    if 'changetype' in document:
                        if 'replace' in document:
                            attribute = document['replace']
                            n1ql_list.append('UPDATE `%s` USE KEYS "%s" SET `%s`=%s' % (cur_bucket, key, attribute, json.dumps(document[attribute])))
                        elif 'add' in document:
                            attribute = document['add']
                            result = self.check_attribute_exists(key, attribute)
                            data = document[attribute]
                            if result:
                                if isinstance(data, list):
                                    for d in data:
                                        n1ql_list.append('UPDATE `%s` USE KEYS "%s" SET `%s`=ARRAY_APPEND(`%s`, %s)' % (cur_bucket, key, attribute, attribute, json.dumps(d)))
                                else:
                                    n1ql_list.append('UPDATE `%s` USE KEYS "%s" SET `%s`=ARRAY_APPEND(`%s`, %s)' % (cur_bucket, key, attribute, attribute, json.dumps(data)))
                            else:
                                if attribute in attribDataTypes.listAttributes and not isinstance(data, list):
                                    data = [data]
                                n1ql_list.append('UPDATE `%s` USE KEYS "%s" SET `%s`=%s' % (cur_bucket, key, attribute, json.dumps(data)))
                    else:
                        n1ql_list.append('UPSERT INTO `%s` (KEY, VALUE) VALUES ("%s", %s)' % (cur_bucket, key, json.dumps(document)))

                    for q in n1ql_list:
                        self.cbm.exec_query(q)

    def import_schema(self, schema_file):
        if self.moddb == BackendTypes.LDAP:
            base.logIt("Importing schema {}".format(schema_file))
            parser = ldif_utils.myLdifParser(schema_file)
            parser.parse()
            for dn, entry in parser.entries:
                if 'changetype' in entry:
                    entry.pop('changetype')
                if 'add' in entry:
                    entry.pop('add')
                for entry_type in entry:
                    for e in entry[entry_type]:
                        base.logIt("Adding to schema, type: {}  value: {}".format(entry_type, e))
                        self.ldap_conn.modify(dn, {entry_type: [ldap3.MODIFY_ADD, e]})

            #we need re-bind after schema operations
            self.ldap_conn.rebind()

    def get_group_for_key(self, key):
        key_prefix = self.get_key_prefix(key)
        for group in Config.couchbaseBucketDict:
            if key_prefix in Config.couchbaseBucketDict[group]['document_key_prefix']:
                break
        else:
            group = 'default'

        return group

    def get_bucket_for_key(self, key):
        group = self.get_group_for_key(key)
        if group == 'default':
            return Config.couchbase_bucket_prefix

        return Config.couchbase_bucket_prefix + '_' + group

    def get_bucket_for_dn(self, dn):
        key = ldif_utils.get_key_from(dn)
        return self.get_bucket_for_key(key)

    def get_backend_location_for_dn(self, dn):
        key = ldif_utils.get_key_from(dn)
        group = self.get_group_for_key(key)
    
        if Config.mappingLocations[group] == 'ldap':
            return static.BackendTypes.LDAP

        if Config.mappingLocations[group] == 'couchbase':
            return static.BackendTypes.COUCHBASE


    def __del__(self):
        try:
            self.ldap_conn.unbind()
            self.ready = False
        except:
            pass


dbUtils = DBUtils()
